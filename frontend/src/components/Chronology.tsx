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

  return (
    <div className={styles.list}>
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
              className={`${styles.entry} ${isSelected ? styles.selected : ""}`}
              onClick={() => onSelect(letter.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSelect(letter.id);
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
