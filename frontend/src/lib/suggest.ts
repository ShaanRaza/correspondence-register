import type { Letter } from "../types";

/**
 * Type-ahead suggestions drawn from THIS package's own text — never a generic
 * dictionary. Typing "pot" should offer "Potholes" only because a letter in the
 * register actually says it, so every suggestion is guaranteed to return
 * results and doubles as a hint at what the package contains.
 */
export interface Suggestion {
  text: string;
  /** Which column it came from, shown as a hint beside the suggestion. */
  kind: "ref" | "subject" | "party" | "chainage" | "clause" | "file" | "thread";
  /** How many letters contain it — the ranking signal. */
  count: number;
}

// Dropped from subject phrases: they match everything and rank noise to the top.
// This is the same failure the search itself had when any single word counted as
// a hit and "of" matched 15 of 16 letters.
const STOPWORDS = new Set([
  "the", "of", "and", "for", "to", "in", "on", "at", "a", "an", "is", "are", "as",
  "with", "from", "by", "or", "be", "it", "its", "this", "that", "under", "into",
  "reg", "sub", "ref", "dated", "sir", "madam", "please", "shall", "may", "no",
]);

function words(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9+/().-]+/i)
    .map((w) => w.replace(/^[-.]+|[-.]+$/g, ""))
    .filter((w) => w.length > 1);
}

/** Title-case for display, but leave anything with digits or punctuation
 *  (references, chainages) exactly as written — those are identifiers. */
function display(raw: string): string {
  if (/[0-9/()]/.test(raw)) return raw;
  return raw.replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

export function buildSuggestions(letters: Letter[]): Suggestion[] {
  const counts = new Map<string, Suggestion>();

  const add = (rawText: string | null | undefined, kind: Suggestion["kind"]) => {
    const text = (rawText ?? "").trim();
    if (text.length < 2) return;
    const key = `${kind}:${text.toLowerCase()}`;
    const existing = counts.get(key);
    if (existing) existing.count += 1;
    else counts.set(key, { text, kind, count: 1 });
  };

  for (const letter of letters) {
    add(letter.letterRef, "ref");
    add(letter.chainage, "chainage");
    add(letter.clause, "clause");
    add(letter.originalFilename, "file");
    add(letter.threadKey, "thread");
    add(letter.from, "party");
    add(letter.to, "party");

    // Subjects carry the vocabulary people actually search by ("potholes",
    // "bus shelter"). Single content words, plus pairs of ADJACENT content
    // words so a real phrase survives while "potholes and" never forms.
    const subjectWords = words(letter.subject ?? "");
    for (let i = 0; i < subjectWords.length; i++) {
      const w = subjectWords[i];
      if (STOPWORDS.has(w)) continue;
      add(display(w), "subject");
      const next = subjectWords[i + 1];
      if (next && !STOPWORDS.has(next)) add(display(`${w} ${next}`), "subject");
    }
  }

  return [...counts.values()];
}

/**
 * Suggestions for what has been typed so far. Matches at a WORD boundary, so
 * "pot" offers "Potholes" and "Pothole Repair" but not "Despot" — mid-word
 * matches are almost never what a prefix query means.
 */
export function matchSuggestions(query: string, index: Suggestion[], limit = 8): Suggestion[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];

  const scored: { s: Suggestion; rank: number }[] = [];
  for (const s of index) {
    const lower = s.text.toLowerCase();
    if (lower === q) continue; // already typed in full
    let rank: number;
    if (lower.startsWith(q)) rank = 0;
    else if (lower.split(/[\s/_-]+/).some((w) => w.startsWith(q))) rank = 1;
    else continue;
    scored.push({ s, rank });
  }

  scored.sort(
    (a, b) =>
      a.rank - b.rank ||
      b.s.count - a.s.count ||
      a.s.text.length - b.s.text.length ||
      a.s.text.localeCompare(b.s.text),
  );
  return scored.slice(0, limit).map((x) => x.s);
}
