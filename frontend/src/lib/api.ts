import type { ExtractedFieldProvenance, Letter, PackageInfo } from "../types";

// The package seeded by `backend/scripts/seed_upload_package.py` for real uploaded
// documents to ingest against -- deliberately not the fictional "NH-44 PKG-3" used
// in the design fixtures, so real evidence is never silently blended with sample data.
//
// `let`, not `const`, and resolved at runtime by bootstrapConfig() below. ES module
// exports are live bindings, so reassigning here updates every importer. Baking the
// id in at build time made each deployment a two-phase dance -- seed the database,
// read the new id, rebuild, redeploy -- and a stale bundle then pointed a live UI at
// a package that no longer existed. The build-time value remains the fallback for
// local dev, where the seeded id is stable and the backend may not be running yet.
export let UPLOAD_PACKAGE_ID = import.meta.env.VITE_UPLOAD_PACKAGE_ID || "51299903-aec7-43c6-9ad0-cc2043578a0d";

// Configurable per deployment. `??` rather than `||` so an explicitly EMPTY
// value is honoured and means "same origin": every request becomes a relative
// URL, which is what lets one process serve the UI and the API together.
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Session cookie auth. The cookie is httpOnly, so it is deliberately invisible
// to this code -- there is nothing to read or attach by hand. `credentials`
// makes the browser send it, which also covers local dev where the frontend and
// API sit on different ports.
function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API_BASE}${path}`, { ...init, credentials: "include" });
}

export interface Session {
  signedIn: boolean;
  email: string | null;
  packageId: string | null;
  /** Whether the server has Google credentials configured. */
  googleEnabled?: boolean;
  /** Whether THIS account may upload. Signing in is open; uploading spends the
   *  server's model credits, so it is the action behind the access code. */
  uploadUnlocked?: boolean;
}

/** Exchanges the access code for a permanent unlock on this account. Stored
 *  server-side against the account, so it is asked once and never again --
 *  on any device, after any sign-out. */
export async function unlockUploads(code: string): Promise<void> {
  const res = await postJson("/api/auth/unlock", { code });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Could not unlock (${res.status})`);
}

/** Full-page redirect, not fetch: OAuth is a browser navigation to Google.
 *  The invite code travels in `state` so a NEW account is still gated by it. */
export function googleSignInUrl(inviteCode: string): string {
  return `${API_BASE}/api/auth/google/start?invite=${encodeURIComponent(inviteCode)}`;
}

function postJson(path: string, body: unknown): Promise<Response> {
  return apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchSession(): Promise<Session> {
  try {
    const res = await apiFetch("/api/auth/me");
    if (!res.ok) return { signedIn: false, email: null, packageId: null };
    return await res.json();
  } catch {
    return { signedIn: false, email: null, packageId: null };
  }
}

export async function signUp(email: string, password: string, inviteCode: string): Promise<Session> {
  const res = await postJson("/api/auth/signup", { email, password, inviteCode });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Sign up failed (${res.status})`);
  UPLOAD_PACKAGE_ID = body.packageId;
  return { signedIn: true, email: body.email, packageId: body.packageId };
}

export async function signIn(email: string, password: string): Promise<Session> {
  const res = await postJson("/api/auth/login", { email, password });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Sign in failed (${res.status})`);
  UPLOAD_PACKAGE_ID = body.packageId;
  return { signedIn: true, email: body.email, packageId: body.packageId };
}

export async function signOut(): Promise<void> {
  await postJson("/api/auth/logout", {});
}

/** One document's ingestion outcome, for the upload history. */
export interface DocumentRecord {
  sha256: string;
  filename: string;
  byteSize: number;
  ingestedAt: string;
  pages: number;
  letters: number;
  status: string;
  error: string | null;
}

export async function fetchDocuments(packageId: string): Promise<DocumentRecord[]> {
  const res = await apiFetch(`/api/packages/${packageId}/documents`);
  if (!res.ok) throw new Error(`Failed to load documents (${res.status})`);
  return res.json();
}

/** Same-origin link; the session cookie rides along automatically. */
export function originalPdfUrl(sha256: string): string {
  return `${API_BASE}/api/documents/${sha256}/original`;
}

/** Resolves the signed-in account's register before the app renders. Failure is
 *  non-fatal: the sign-in screen renders and the real error surfaces there. */
export async function bootstrapConfig(): Promise<Session> {
  try {
    const res = await fetch(`${API_BASE}/api/config`, { credentials: "include" });
    if (!res.ok) return { signedIn: false, email: null, packageId: null };
    const json = await res.json();
    if (json.packageId) UPLOAD_PACKAGE_ID = json.packageId;
    return { signedIn: !!json.signedIn, email: json.email ?? null, packageId: json.packageId ?? null };
  } catch {
    return { signedIn: false, email: null, packageId: null };
  }
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
