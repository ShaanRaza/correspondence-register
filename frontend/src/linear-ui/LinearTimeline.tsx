import type { Letter } from "../types";
import { formatDate } from "../lib/dates";
import { computeGaps, sortChronologically } from "../lib/thread";
import styles from "./LinearTimeline.module.css";

export function LinearTimeline({
  letters,
  selectedId,
  onSelect,
}: {
  letters: Letter[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const sorted = sortChronologically(letters);
  const gaps = computeGaps(sorted);

  return (
    <div className={styles.list} role="listbox" aria-label="Thread timeline">
      <div className={styles.line} />
      {sorted.map((letter, i) => {
        const gap = gaps[i];
        const isSelected = letter.id === selectedId;
        return (
          <div key={letter.id}>
            {gap && (
              <div className={styles.gapWrap}>
                <span className={styles.gapPill}>{gap.days} d</span>
                <span className={styles.gapCaption}>
                  {gap.fromRef} ({formatDate(gap.fromDated)}) → {gap.toRef} (
                  {formatDate(gap.toDated)})
                </span>
              </div>
            )}
            <div className={styles.node}>
              <div className={`${styles.dot} ${isSelected ? styles.dotSelected : ""}`} />
              <div
                className={`${styles.card} ${isSelected ? styles.cardSelected : ""}`}
                role="option"
                aria-selected={isSelected}
                tabIndex={0}
                onClick={() => onSelect(letter.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onSelect(letter.id);
                }}
              >
                <div className={styles.cardHead}>
                  <span className={styles.subject}>{letter.subject}</span>
                  {letter.reviewStatus === "needs_review" && (
                    <span className={`${styles.badge} ${styles.badgeReview}`}>Review</span>
                  )}
                  {letter.reviewStatus === "verified" && (
                    <span className={`${styles.badge} ${styles.badgeVerified}`}>Verified</span>
                  )}
                </div>
                <div className={styles.meta}>
                  <span className={styles.metaRef}>{letter.letterRef}</span>
                  <span>·</span>
                  <span>
                    {letter.from} → {letter.to}
                  </span>
                  <span>·</span>
                  <span>{formatDate(letter.dated)}</span>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
