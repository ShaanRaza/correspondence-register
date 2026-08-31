import { useState } from "react";
import type { AmbiguousCitation } from "../lib/api";
import { confirmCitation } from "../lib/api";
import styles from "./LinearCitationReviewPanel.module.css";

/* The review queue for citations the pipeline could plausibly match but never
   auto-links -- see link.py: the digits that would tell two real letters apart
   are exactly what OCR corrupts most, so a fuzzy match is a candidate, not a
   fact. Confirming here is the only action in the whole system that turns one
   into a resolved link and threads the two letters together. */
export function LinearCitationReviewPanel({
  open,
  onClose,
  citations,
  onConfirmed,
}: {
  open: boolean;
  onClose: () => void;
  citations: AmbiguousCitation[];
  onConfirmed: () => void;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleConfirm = async (citationId: string, candidateLetterId: string) => {
    setPending(`${citationId}:${candidateLetterId}`);
    setError(null);
    try {
      await confirmCitation(citationId, candidateLetterId);
      onConfirmed();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(null);
    }
  };

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <span className={styles.title}>Review possible citation matches ({citations.length})</span>
          <button className={styles.close} onClick={onClose}>
            Close
          </button>
        </div>
        <div className={styles.body}>
          {citations.length === 0 && (
            <div className={styles.empty}>No ambiguous citations to review right now.</div>
          )}
          {citations.map((c) => (
            <div key={c.citationId} className={styles.item}>
              <div className={styles.itemHead}>
                <b>Serial {c.citingSerial}</b> ({c.citingLetterRef}) cites “{c.citedRefText}”
              </div>
              {c.candidates.map((cand) => {
                const key = `${c.citationId}:${cand.candidateLetterId}`;
                return (
                  <div key={key} className={styles.candidateRow}>
                    <span className={styles.candidateInfo}>
                      Serial {cand.candidateSerial} — {cand.candidateLetterRef}
                    </span>
                    {cand.matchScore != null && (
                      <span className={styles.candidateScore}>{Math.round(cand.matchScore * 100)}% similar</span>
                    )}
                    <button
                      className={styles.confirmButton}
                      disabled={pending === key}
                      onClick={() => handleConfirm(c.citationId, cand.candidateLetterId)}
                    >
                      {pending === key ? "Confirming…" : "Confirm match"}
                    </button>
                  </div>
                );
              })}
            </div>
          ))}
          {error && <div className={styles.itemHead}>{error}</div>}
        </div>
      </div>
    </div>
  );
}
