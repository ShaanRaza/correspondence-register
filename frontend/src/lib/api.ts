import type { ExtractedFieldProvenance, Letter, PackageInfo } from "../types";

// The package seeded by `backend/scripts/seed_upload_package.py` for real uploaded
// documents to ingest against -- deliberately not the fictional "NH-44 PKG-3" used
// in the design fixtures, so real evidence is never silently blended with sample data.
// Overridable per deployment: each deployed backend has its own fresh database
// with its own seeded package_id, distinct from your local one.
export const UPLOAD_PACKAGE_ID = import.meta.env.VITE_UPLOAD_PACKAGE_ID || "51299903-aec7-43c6-9ad0-cc2043578a0d";

// Configurable per deployment. `??` rather than `||` so an explicitly EMPTY
// value is honoured and means "same origin": every request becomes a relative
// URL. That is what lets one process serve the UI and the API behind a single
// tunnel whose hostname is random and changes on restart -- the bundle never
// has to know its own public address, and there is no CORS in play. Unset (the
// local-dev case) still falls back to the separate backend port.
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Shared-password gate (see backend/app/main.py's `require_app_password`
// middleware) -- not real per-user auth, just a stop against a random
// link-holder touching a deployed instance. Stored per-browser, attached to
// every request; a no-op when the backend has no APP_PASSWORD configured.
const APP_PASSWORD_STORAGE = "correspondence_register_app_password";

export function getStoredAppPassword(): string {
  try {
    return localStorage.getItem(APP_PASSWORD_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setStoredAppPassword(password: string): void {
  try {
    if (password) localStorage.setItem(APP_PASSWORD_STORAGE, password);
    else localStorage.removeItem(APP_PASSWORD_STORAGE);
  } catch {
    // Private browsing / storage disabled.
  }
}

function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const password = getStoredAppPassword();
  const headers = new Headers(init.headers);
  if (password) headers.set("X-App-Password", password);
  return fetch(`${API_BASE}${path}`, { ...init, headers });
}

/** Used by the lock screen to validate a password before letting the app render. */
export async function checkAppPassword(password: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/packages/${UPLOAD_PACKAGE_ID}`, {
    headers: { "X-App-Password": password },
  });
  return res.status !== 401;
}

export interface UploadResult {
  documentSha256: string;
  isDuplicate: boolean;
  lettersFound: number;
  // Candidate letters this document contained that matched an already-registered
  // letter_ref -- a re-scan or duplicate submission, merged into the existing
  // register row rather than creating a second one.
  matchedExisting: { letterRef: string | null; existingLetterId: string }[];
}

// Lets a second person use their own OpenAI quota against a shared instance
// without touching the server's .env. Stored only in this browser (localStorage
// is per-origin, never sent anywhere on its own) and attached per-upload; never
// written to any backend file, database row, or log.
const OPENAI_KEY_STORAGE = "correspondence_register_openai_key";

export function getStoredOpenAIKey(): string {
  try {
    return localStorage.getItem(OPENAI_KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setStoredOpenAIKey(key: string): void {
  try {
    if (key) localStorage.setItem(OPENAI_KEY_STORAGE, key);
    else localStorage.removeItem(OPENAI_KEY_STORAGE);
  } catch {
    // Private browsing / storage disabled -- the key just won't persist across reloads.
  }
}

export async function uploadDocument(packageId: string, file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const storedKey = getStoredOpenAIKey();
  if (storedKey) form.append("openai_api_key", storedKey);
  const res = await apiFetch(`/api/packages/${packageId}/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Upload failed (${res.status})`);
  }
  const json = await res.json();
  return {
    documentSha256: json.document_sha256,
    isDuplicate: json.is_duplicate,
    lettersFound: json.letters_found,
    matchedExisting: (json.matched_existing || []).map((m: { letter_ref: string | null; existing_letter_id: string }) => ({
      letterRef: m.letter_ref,
      existingLetterId: m.existing_letter_id,
    })),
  };
}

export function describeUploadResult(filename: string, result: UploadResult): string {
  if (result.isDuplicate) return `${filename}: already ingested`;
  if (result.matchedExisting.length > 0) {
    const refs = result.matchedExisting.map((m) => m.letterRef).filter(Boolean).join(", ");
    const newPart = result.lettersFound > 0 ? `, ${result.lettersFound} new` : "";
    return `${filename}: merged into existing ${refs || "letter(s)"}${newPart}`;
  }
  return `${filename}: ${result.lettersFound} letter(s) found`;
}

export async function fetchLetters(packageId: string): Promise<Letter[]> {
  const res = await apiFetch(`/api/packages/${packageId}/letters`);
  if (!res.ok) throw new Error(`Failed to load letters (${res.status})`);
  return res.json();
}

export async function fetchLetterFields(letterId: string): Promise<ExtractedFieldProvenance[]> {
  const res = await apiFetch(`/api/letters/${letterId}/fields`);
  if (!res.ok) throw new Error(`Failed to load field sources (${res.status})`);
  return res.json();
}

// A plain <img src> can't carry the X-App-Password header, and the password
// must never go in a URL/query string -- so this fetches the image as a blob
// (with the header attached, same as every other request) and hands back an
// object URL instead. Caller owns revoking it (URL.revokeObjectURL) once done.
export async function fetchRasterObjectUrl(documentSha256: string, pageNo: number): Promise<string> {
  const res = await apiFetch(`/api/documents/${documentSha256}/pages/${pageNo}/raster`);
  if (!res.ok) throw new Error(`Failed to load page image (${res.status})`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export interface AmbiguousCitationCandidate {
  candidateLetterId: string;
  candidateLetterRef: string | null;
  candidateSerial: number;
  matchMethod: string;
  matchScore: number | null;
}

export interface AmbiguousCitation {
  citationId: string;
  citingLetterId: string;
  citingLetterRef: string | null;
  citingSerial: number;
  citedRefText: string | null;
  candidates: AmbiguousCitationCandidate[];
}

export async function fetchAmbiguousCitations(packageId: string): Promise<AmbiguousCitation[]> {
  const res = await apiFetch(`/api/packages/${packageId}/citations/ambiguous`);
  if (!res.ok) throw new Error(`Failed to load ambiguous citations (${res.status})`);
  return res.json();
}

export async function confirmCitation(citationId: string, candidateLetterId: string): Promise<void> {
  const res = await apiFetch(`/api/citations/${citationId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_letter_id: candidateLetterId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to confirm (${res.status})`);
  }
}

export async function fetchPackageInfo(packageId: string): Promise<PackageInfo> {
  const res = await apiFetch(`/api/packages/${packageId}`);
  if (!res.ok) throw new Error(`Failed to load package (${res.status})`);
  const json = await res.json();
  return {
    name: json.name,
    contractNo: json.contractNo,
    periodFrom: "",
    periodTo: "",
    documentsIngested: json.documentsIngested,
    documentsTotal: json.documentsTotal,
  };
}
