import { useState } from "react";
import type { Letter, PackageInfo } from "../types";
import { runQuery, type QueryResult } from "../lib/query";
import { formatDate } from "../lib/dates";
import styles from "./QueryPanel.module.css";

function ResultView({ result }: { result: QueryResult | null }) {
  if (result === null) {
    return (
      <div className={styles.hint}>
        Retrieval over this package's register data only. Every result names the letter
        it came from. Try a package name, a party, a chainage, or a word from a subject
        line.
      </div>
    );
  }

  if (result.kind === "package_summary") {
    const { pkg, letterCount, needsReviewCount, threadCount, spanDays } = result;
    return (
      <div>
        <div className={styles.summaryLabel}>{pkg.name}</div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Contract</span>
          <span className={styles.summaryValue}>{pkg.contractNo}</span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Period</span>
          <span className={styles.summaryValue}>
            {formatDate(pkg.periodFrom)} – {formatDate(pkg.periodTo)} ({spanDays} d)
          </span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Documents</span>
          <span className={styles.summaryValue}>
            {pkg.documentsIngested} of {pkg.documentsTotal} ingested
          </span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Letters</span>
          <span className={styles.summaryValue}>{letterCount}</span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Threads</span>
          <span className={styles.summaryValue}>{threadCount}</span>
        </div>
        <div className={styles.summaryRow}>
          <span className={styles.summaryKey}>Needs review</span>
          <span className={styles.summaryValue}>{needsReviewCount}</span>
        </div>
      </div>
    );
  }

  if (result.kind === "letter_matches") {
    return (
      <div>
        <div className={styles.hitCount}>
          {result.hits.length} letter{result.hits.length === 1 ? "" : "s"} match
          {result.hits.length === 1 ? "es" : ""} "{result.query}"
        </div>
        {result.hits.map((hit) => (
          <div key={hit.letter.id} className={styles.hit}>
            <div className={styles.hitSubject}>{hit.letter.subject}</div>
            <div className={styles.hitCitation}>
              Serial {hit.letter.serial} · {hit.letter.letterRef} ·{" "}
              {formatDate(hit.letter.dated)} · matched on {hit.matchedOn.join(", ")}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return <div className={styles.noMatch}>No matching correspondence found for "{result.query}".</div>;
}

export function QueryPanel({
  open,
  onClose,
  letters,
  pkg,
}: {
  open: boolean;
  onClose: () => void;
  letters: Letter[];
  pkg: PackageInfo;
}) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);

  if (!open) return null;

  const submit = () => setResult(runQuery(text, letters, pkg));

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.label}>Query</span>
        <button className={styles.close} onClick={onClose}>
          Close
        </button>
      </div>
      <div className={styles.inputRow}>
        <input
          autoFocus
          className={styles.input}
          placeholder="e.g. NH-44 PKG-3, site handover, Km 12+400"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
      </div>
      <div className={styles.results}>
        <ResultView result={result} />
      </div>
    </div>
  );
}
