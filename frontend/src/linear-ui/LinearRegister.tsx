import type { Letter } from "../types";
import { formatDate, daysBetween } from "../lib/dates";
import styles from "./LinearRegister.module.css";

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

function StatusBadge({ letter }: { letter: Letter }) {
  if (letter.reviewStatus === "needs_review") {
    return <span className={`${styles.badge} ${styles.badgeReview}`}>Review</span>;
  }
  if (letter.reviewStatus === "verified") {
    return <span className={`${styles.badge} ${styles.badgeVerified}`}>Verified</span>;
  }
  return <span className={`${styles.badge} ${styles.badgeNeutral}`}>Unverified</span>;
}

export function LinearRegister({
  letters,
  onOpen,
}: {
  letters: Letter[];
  onOpen: (letter: Letter) => void;
}) {
  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        <thead className={styles.thead}>
          <tr>
            {HEADS.map((h) => (
              <th
                key={h}
                className={`${styles.th} ${h === "Sr" || h === "Reply in" ? styles.thRight : ""}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {letters.length === 0 ? (
            <tr>
              <td colSpan={HEADS.length} className={styles.empty}>
                No documents match these filters.
              </td>
            </tr>
          ) : (
            letters.map((l) => {
              const replyDays =
                l.repliesToDated != null ? daysBetween(l.repliesToDated, l.dated) : null;
              return (
                <tr
                  key={l.id}
                  className={styles.row}
                  tabIndex={0}
                  onClick={() => onOpen(l)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onOpen(l);
                  }}
                >
                  <td className={styles.td}>
                    <StatusBadge letter={l} />
                  </td>
                  <td className={`${styles.td} ${styles.tdRight} ${styles.tdMuted}`}>
                    {l.serial}
                  </td>
                  <td className={styles.td}>{formatDate(l.dated)}</td>
                  <td className={`${styles.td} ${styles.tdMuted}`}>
                    {l.received ? formatDate(l.received) : "—"}
                  </td>
                  <td className={`${styles.td} ${styles.tdMuted}`}>
                    {l.unresolvedField === "parties" ? "—" : `${l.from} → ${l.to}`}
                  </td>
                  <td className={styles.td}>{l.letterRef}</td>
                  <td className={styles.td}>
                    <span className={styles.subject}>{l.subject}</span>
                    {l.missingCitation && (
                      <span className={styles.subjectMissing}>
                        cites {l.missingCitation}, not held
                      </span>
                    )}
                  </td>
                  <td className={`${styles.td} ${styles.tdMuted}`}>
                    {l.unresolvedField === "chainage" ? "—" : l.chainage ?? "—"}
                  </td>
                  <td className={`${styles.td} ${styles.tdMuted}`}>
                    {l.unresolvedField === "clause" ? "—" : l.clause ?? "—"}
                  </td>
                  <td className={`${styles.td} ${styles.tdMuted}`}>{l.threadKey}</td>
                  <td className={`${styles.td} ${styles.tdRight}`}>
                    {replyDays != null ? `${replyDays} d` : "—"}
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
