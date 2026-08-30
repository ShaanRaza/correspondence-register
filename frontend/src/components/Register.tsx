import { useEffect, useRef, useState } from "react";
import type { Letter } from "../types";
import { formatDate, daysBetween } from "../lib/dates";
import styles from "./Register.module.css";

const HEADS = [
  "Status",
  "Sr",
  "Dated",
  "Received",
  "Parties",
  "Letter ref",
  "Subject",
  "Chainage",
  "Clause",
  "Thread",
  "Reply in",
];

function StatusCell({ letter }: { letter: Letter }) {
  if (letter.reviewStatus === "needs_review") {
    return (
      <div className={`${styles.statusCell} ${styles.statusReview}`}>
        <div className={styles.statusBar} />
        <div className={styles.statusWord}>Review</div>
      </div>
    );
  }
  if (letter.reviewStatus === "verified") {
    return (
      <div className={`${styles.statusCell} ${styles.statusVerified}`}>
        <div className={styles.statusBar} />
        <div className={styles.statusWord}>Verified</div>
      </div>
    );
  }
  // unverified: absence is data — no bar, no word, per DESIGN.md.
  return <div className={styles.statusCell} />;
}

function Dash() {
  return <span className={styles.emptyDash}>—</span>;
}

export function Register({
  letters,
  onOpen,
}: {
  letters: Letter[];
  onOpen: (letter: Letter) => void;
}) {
  const [focusedIndex, setFocusedIndex] = useState(0);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);

  // A filtered result set can shrink out from under a stale focused index (e.g.
  // typing a chainage filter while row 8 is focused, leaving only 3 rows).
  useEffect(() => {
    if (focusedIndex > letters.length - 1) setFocusedIndex(0);
  }, [letters.length, focusedIndex]);

  const moveFocus = (nextIndex: number) => {
    const clamped = Math.max(0, Math.min(letters.length - 1, nextIndex));
    setFocusedIndex(clamped);
    rowRefs.current[clamped]?.focus();
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.headRow}>
        {HEADS.map((h) => (
          <div key={h} className={styles.headCell}>
            {h}
          </div>
        ))}
      </div>

      {letters.length === 0 ? (
        <div style={{ padding: "8px 12px", color: "var(--ink-2)", fontSize: 13 }}>
          No documents match these filters.
        </div>
      ) : (
        letters.map((l, i) => {
          const replyDays =
            l.repliesToDated != null ? daysBetween(l.repliesToDated, l.dated) : null;

          return (
            <div
              className={styles.row}
              key={l.id}
              ref={(el) => {
                rowRefs.current[i] = el;
              }}
              role="button"
              tabIndex={i === focusedIndex ? 0 : -1}
              onClick={() => onOpen(l)}
              onFocus={() => setFocusedIndex(i)}
              onKeyDown={(e) => {
                switch (e.key) {
                  case "Enter":
                    onOpen(l);
                    break;
                  case "ArrowDown":
                    e.preventDefault();
                    moveFocus(i + 1);
                    break;
                  case "ArrowUp":
                    e.preventDefault();
                    moveFocus(i - 1);
                    break;
                  case "Home":
                    e.preventDefault();
                    moveFocus(0);
                    break;
                  case "End":
                    e.preventDefault();
                    moveFocus(letters.length - 1);
                    break;
                }
              }}
              style={{ cursor: "pointer" }}
            >
              <div className={`${styles.cell} ${styles.statusOuterCell}`}>
                <StatusCell letter={l} />
              </div>
              <div className={`${styles.cell} ${styles.mono} ${styles.right}`}>{l.serial}</div>
              <div className={`${styles.cell} ${styles.mono}`}>{formatDate(l.dated)}</div>
              <div className={`${styles.cell} ${styles.mono}`}>
                {l.received ? formatDate(l.received) : <Dash />}
              </div>
              <div className={`${styles.cell} ${styles.parties}`}>
                {l.from} → {l.to}
              </div>
              <div className={`${styles.cell} ${styles.mono}`}>{l.letterRef}</div>
              <div className={`${styles.cell} ${styles.subjectCell}`}>
                {l.subject}
                {l.missingCitation && (
                  <span style={{ color: "var(--flag-review)", marginLeft: 6 }}>
                    · cites {l.missingCitation}, not held
                  </span>
                )}
              </div>
              <div className={`${styles.cell} ${styles.mono}`}>
                {l.unresolvedField === "chainage" ? <Dash /> : l.chainage ?? <Dash />}
              </div>
              <div className={`${styles.cell} ${styles.mono}`}>
                {l.unresolvedField === "clause" ? <Dash /> : l.clause ?? <Dash />}
              </div>
              <div className={`${styles.cell} ${styles.mono}`}>{l.threadKey}</div>
              <div className={`${styles.cell} ${styles.mono} ${styles.right} ${styles.replyIn}`}>
                {replyDays != null ? `${replyDays} d` : <Dash />}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
