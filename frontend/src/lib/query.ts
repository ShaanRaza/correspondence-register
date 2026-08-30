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
    };

    const matchedOn: string[] = [];
    for (const [fieldName, value] of Object.entries(fields)) {
      const normValue = normalize(value);
      if (words.some((w) => normValue.includes(w))) {
        matchedOn.push(fieldName);
      }
    }

    if (matchedOn.length > 0) hits.push({ letter, matchedOn });
  }

  if (hits.length === 0) return { kind: "no_match", query: rawQuery };

  hits.sort((a, b) => b.matchedOn.length - a.matchedOn.length || a.letter.serial - b.letter.serial);
  return { kind: "letter_matches", query: rawQuery, hits };
}
