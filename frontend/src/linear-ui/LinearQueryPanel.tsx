import type { QueryResult } from "../lib/query";
import { formatDate } from "../lib/dates";
import styles from "./LinearQueryPanel.module.css";

// Same deterministic, cited retrieval as the shipped QueryPanel (lib/query.ts,
// unchanged) — restyled only. The search input itself now lives in LinearTitleBar,
// always visible, rather than hidden inside this panel behind a click — this
// component is purely the results display now.
function ResultView({ result }: { result: QueryResult | null }) {
  if (result === null) {
    return (
      <div className={styles.hint}>
        Retrieval over this package's register data only. Try a package name, a party,
        a chainage, or a word from a subject line.
      </div>
    );
  }

  if (result.kind === "package_summary") {
    const { pkg, letterCount, needsReviewCount, threadCount, spanDays } = result;
    return (
      <div className={styles.summaryCard}>
        <div className={styles.summaryTitle}>{pkg.name}</div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Contract</span>
          <span>{pkg.contractNo}</span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Period</span>
          <span>
            {formatDate(pkg.periodFrom)} – {formatDate(pkg.periodTo)} ({spanDays} d)
          </span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Documents</span>
          <span>
            {pkg.documentsIngested} of {pkg.documentsTotal}
          </span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Letters</span>
          <span>{letterCount}</span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Threads</span>
          <span>{threadCount}</span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Needs review</span>
          <span>{needsReviewCount}</span>
        </div>
      </div>
    );
  }

  if (result.kind === "letter_matches") {
    return (
      <div>
        <div className={styles.hitCount}>
          {result.hits.length} letter{result.hits.length === 1 ? "" : "s"} match "
          {result.query}"
        </div>
        {result.hits.map((hit) => (
          <div key={hit.letter.id} className={styles.hit}>
            <div className={styles.hitSubject}>{hit.letter.subject}</div>
            <div className={styles.hitCitation}>
              Serial {hit.letter.serial} · {hit.letter.letterRef} ·{" "}
              {formatDate(hit.letter.dated)}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return <div className={styles.noMatch}>No matching correspondence found for "{result.query}".</div>;
}

export function LinearQueryPanel({
  open,
  onClose,
  result,
}: {
  open: boolean;
  onClose: () => void;
  result: QueryResult | null;
}) {
  if (!open) return null;

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.title}>Search results</span>
        <button className={styles.close} onClick={onClose}>
          Close
        </button>
      </div>
      <div className={styles.results}>
        <ResultView result={result} />
      </div>
    </div>
  );
}
