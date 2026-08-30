import { useRef } from "react";
import type { Letter } from "../types";
import { formatDate } from "../lib/dates";
import { computeGaps } from "../lib/thread";
import styles from "./Chronology.module.css";

export function Chronology({
  letters,
  selectedId,
  onSelect,
}: {
  letters: Letter[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const sorted = [...letters].sort((a, b) => a.serial - b.serial);
  const gaps = computeGaps(sorted);
  const entryRefs = useRef<(HTMLDivElement | null)[]>([]);

  const moveSelection = (nextIndex: number) => {
    const clamped = Math.max(0, Math.min(sorted.length - 1, nextIndex));
    onSelect(sorted[clamped].id);
    entryRefs.current[clamped]?.focus();
  };

  return (
    <div className={styles.list} role="listbox" aria-label="Thread chronology">
      {sorted.map((letter, i) => {
        const gap = gaps[i];
        const isSelected = letter.id === selectedId;
        return (
          <div key={letter.id}>
            {gap && (
              <div className={styles.gap}>
                <span className={styles.gapFigure}>{gap.days} d</span>
                <span className={styles.gapEndpoints}>
                  {gap.fromRef} · {formatDate(gap.fromDated)} → {gap.toRef} ·{" "}
                  {formatDate(gap.toDated)}
                </span>
              </div>
            )}
            <div
              ref={(el) => {
                entryRefs.current[i] = el;
              }}
              className={`${styles.entry} ${isSelected ? styles.selected : ""}`}
              onClick={() => onSelect(letter.id)}
              role="option"
              aria-selected={isSelected}
              aria-label={`Serial ${letter.serial}, ${letter.letterRef}, ${formatDate(letter.dated)}, ${letter.subject}`}
              tabIndex={isSelected ? 0 : -1}
              onKeyDown={(e) => {
                switch (e.key) {
                  case "Enter":
                    onSelect(letter.id);
                    break;
                  case "ArrowDown":
                    e.preventDefault();
                    moveSelection(i + 1);
                    break;
                  case "ArrowUp":
                    e.preventDefault();
                    moveSelection(i - 1);
                    break;
                  case "Home":
                    e.preventDefault();
                    moveSelection(0);
                    break;
                  case "End":
                    e.preventDefault();
                    moveSelection(sorted.length - 1);
                    break;
                }
              }}
            >
              <div className={styles.entryHead}>
                <span className={styles.serial}>{letter.serial}</span>
                <span className={styles.dated}>{formatDate(letter.dated)}</span>
                <span className={styles.ref}>{letter.letterRef}</span>
                {letter.reviewStatus === "needs_review" && (
                  <span className={`${styles.statusWord} ${styles.statusReview}`}>Review</span>
                )}
                {letter.reviewStatus === "verified" && (
                  <span className={`${styles.statusWord} ${styles.statusVerified}`}>Verified</span>
                )}
                <span className={styles.parties}>
                  {letter.from} → {letter.to}
                </span>
              </div>
              <div className={styles.subject}>{letter.subject}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
