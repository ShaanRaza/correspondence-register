import type { Letter } from "../types";
import { daysBetween } from "./dates";

export interface ThreadGap {
  days: number;
  fromRef: string;
  fromDated: string;
  toRef: string;
  toDated: string;
}

/** Chronological order: by the date on the letterhead, oldest first.
 *
 * Sorting by `serial` instead — as both timeline views previously did — orders
 * a thread by the order documents happened to be UPLOADED, which for real
 * uploads has nothing to do with when the correspondence happened. A thread
 * then ran 27 Aug -> 25 Jun and the elapsed-days gap between them rendered as
 * "-63 d". Elapsed time between consecutive letters is the whole point of a
 * chronology (and of the extension-of-time argument it supports), so a
 * negative gap is not a display quirk -- it means the sequence is wrong.
 *
 * `serial` breaks ties so same-day letters keep a stable, register-consistent
 * order, and letters with no readable date sort last rather than corrupting
 * the gaps between letters that do have one.
 */
export function sortChronologically(letters: Letter[]): Letter[] {
  return [...letters].sort((a, b) => {
    if (!a.dated && !b.dated) return a.serial - b.serial;
    if (!a.dated) return 1;
    if (!b.dated) return -1;
    return a.dated.localeCompare(b.dated) || a.serial - b.serial;
  });
}

/** Elapsed days between each letter and the one immediately before it in
   chronological order — the same deterministic, non-inferred definition used in
   the register (PIPELINE.md's REPLY IN: previous letter in the thread by dated
   order, never a guess about which citation is "the" reply target). */
export function computeGaps(sortedLetters: Letter[]): (ThreadGap | null)[] {
  return sortedLetters.map((letter, i) => {
    if (i === 0) return null;
    const prev = sortedLetters[i - 1];
    return {
      days: daysBetween(prev.dated, letter.dated),
      fromRef: prev.letterRef,
      fromDated: prev.dated,
      toRef: letter.letterRef,
      toDated: letter.dated,
    };
  });
}
