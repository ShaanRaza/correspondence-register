import type { Letter } from "../types";
import { daysBetween } from "./dates";

export interface ThreadGap {
  days: number;
  fromRef: string;
  fromDated: string;
  toRef: string;
  toDated: string;
}

/** Elapsed days between each letter and the one immediately before it in serial
   order — the same deterministic, non-inferred definition used in the register
   (PIPELINE.md's REPLY IN: previous letter in the thread by dated order, never a
   guess about which citation is "the" reply target). */
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
