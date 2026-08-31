import type { Letter, PackageInfo } from "../types";
import { daysBetween, formatDate } from "./dates";

/**
 * Deterministic, cited retrieval over the register — not a language model. Every
 * result names the exact letter(s) it came from. This exists specifically because
 * PRODUCT.md rules out a conversational chatbot over these documents: an assistant
 * that free-answers "tell me about this" is interpretation, which is the one thing
 * this tool has no standing to offer in front of a tribunal. Retrieval only.
 */

export interface PackageSummaryResult {
  kind: "package_summary";
  pkg: PackageInfo;
  letterCount: number;
  needsReviewCount: number;
  threadCount: number;
  spanDays: number;
}

export interface LetterHit {
  letter: Letter;
  matchedOn: string[];
  /** True when one field contains the whole query as a contiguous phrase. */
  phraseHit?: boolean;
}

export interface LetterMatchesResult {
  kind: "letter_matches";
  query: string;
  hits: LetterHit[];
}

export interface NoMatchResult {
  kind: "no_match";
  query: string;
}

export type QueryResult = PackageSummaryResult | LetterMatchesResult | NoMatchResult;

function normalize(s: string): string {
  return s.trim().toLowerCase();
}

export function runQuery(rawQuery: string, letters: Letter[], pkg: PackageInfo): QueryResult {
  const query = normalize(rawQuery);
  if (!query) return { kind: "no_match", query: rawQuery };

  const packageTokens = [pkg.name, pkg.contractNo].map(normalize);
  if (packageTokens.some((t) => t.includes(query) || query.includes(t))) {
    const threadKeys = new Set(letters.map((l) => l.threadKey));
    const dates = letters.map((l) => l.dated).sort();
    return {
      kind: "package_summary",
      pkg,
      letterCount: letters.length,
      needsReviewCount: letters.filter((l) => l.reviewStatus === "needs_review").length,
      threadCount: threadKeys.size,
      spanDays: daysBetween(dates[0], dates[dates.length - 1]),
    };
  }

  const words = query.split(/\s+/).filter(Boolean);
  const hits: LetterHit[] = [];

  for (const letter of letters) {
    const fields: Record<string, string> = {
      "letter ref": letter.letterRef,
      subject: letter.subject,
      chainage: letter.chainage ?? "",
      clause: letter.clause ?? "",
      parties: `${letter.from} ${letter.to}`,
      dated: formatDate(letter.dated),
      // Searching by the uploaded file's name previously matched nothing at
      // all: the filename was never returned by the API, let alone searched.
      // Same for the thread key, which made threads unfindable by name.
      thread: letter.threadKey,
      "source file": letter.originalFilename ?? "",
    };

    const entries = Object.entries(fields).map(
      ([name, value]) => [name, normalize(value)] as const,
    );

    // EVERY word must appear somewhere in the letter, not just one of them.
    // Matching on any single word made the search useless in practice: a query
    // like "Shifting of Box Culvert" matched 15 of 16 letters, because the word
    // "of" occurs in nearly every subject line. Requiring all words is what a
    // search box is expected to do, and it is what makes a filename or a
    // multi-word subject phrase actually narrow the register down.
    const everyWordFound = words.every((w) =>
      entries.some(([, value]) => value.includes(w)),
    );
    if (!everyWordFound) continue;

    const matchedOn = entries
      .filter(([, value]) => words.some((w) => value.includes(w)))
      .map(([name]) => name);

    // A field containing the entire query as one phrase is a stronger signal
    // than the same words scattered across different fields; used for ranking.
    const phraseHit = entries.some(([, value]) => value.includes(query));
    hits.push({ letter, matchedOn, phraseHit });
  }

  if (hits.length === 0) return { kind: "no_match", query: rawQuery };

  hits.sort(
    (a, b) =>
      Number(b.phraseHit ?? false) - Number(a.phraseHit ?? false) ||
      b.matchedOn.length - a.matchedOn.length ||
      a.letter.serial - b.letter.serial,
  );
  return { kind: "letter_matches", query: rawQuery, hits };
}
