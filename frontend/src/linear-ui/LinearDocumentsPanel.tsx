import { useEffect, useState } from "react";
import { fetchDocuments, originalPdfUrl, type DocumentRecord } from "../lib/api";
import styles from "./LinearDocumentsPanel.module.css";

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Everything uploaded to this register and what became of it.
 *
 * Its real job is the failures: a document whose extraction failed is simply
 * ABSENT from the register, which is indistinguishable from never having been
 * uploaded. Listing it with its reason is what makes the register's
 * completeness checkable rather than assumed.
 */
export function LinearDocumentsPanel({
  open,
  onClose,
  packageId,
  refreshKey,
}: {
  open: boolean;
  onClose: () => void;
  packageId: string;
  /** Changes when a batch finishes, so the list reflects it without a reload. */
  refreshKey?: number;
}) {
  const [docs, setDocs] = useState<DocumentRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDocs(null);
    setError(null);
    fetchDocuments(packageId).then(setDocs).catch((e) => setError((e as Error).message));
  }, [open, packageId, refreshKey]);

  if (!open) return null;

  const failed = docs?.filter((d) => d.status === "failed").length ?? 0;

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <span className={styles.title}>
            Uploaded documents{docs ? ` (${docs.length}${failed ? `, ${failed} failed` : ""})` : ""}
          </span>
          <button className={styles.close} onClick={onClose}>Close</button>
        </div>
        <div className={styles.body}>
          {error && <div className={styles.empty}>Could not load documents — {error}</div>}
          {!error && docs === null && <div className={styles.empty}>Loading…</div>}
          {!error && docs?.length === 0 && (
            <div className={styles.empty}>
              Nothing uploaded yet. Documents you upload stay here — you never need to upload
              them again.
            </div>
          )}
          {docs?.map((d) => (
            <div className={styles.row} key={d.sha256}>
              <span className={styles.name} title={d.filename}>{d.filename}</span>
              <span className={styles.meta}>
                {formatWhen(d.ingestedAt)} · {formatSize(d.byteSize)} · {d.pages} pg ·{" "}
                {d.letters} letter{d.letters === 1 ? "" : "s"}
              </span>
              <span
                className={`${styles.badge} ${
                  d.status === "succeeded" ? styles.ok : d.status === "failed" ? styles.failed : styles.other
                }`}
              >
                {d.status}
              </span>
              <a className={styles.download} href={originalPdfUrl(d.sha256)} download>
                Original
              </a>
              {d.error && <div className={styles.error}>{d.error}</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
