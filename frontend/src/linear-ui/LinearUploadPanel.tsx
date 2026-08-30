import styles from "./LinearUploadPanel.module.css";

/**
 * Visual placeholder only, deliberately not wired to anything — the author chose
 * this over building real ingestion. No backend is connected to either UI in this
 * project; PIPELINE.md's actual ingestion pipeline (S0–S8, OCR, extraction,
 * validation) exists only as backend code (reprocessing.py, jobs.py) with no
 * upload endpoint and no frontend wiring. This panel exists so the feature has a
 * visible home, and says so honestly rather than pretending a drop here does
 * anything.
 */
export function LinearUploadPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.title}>Upload documents</span>
        <button className={styles.close} onClick={onClose}>
          Close
        </button>
      </div>
      <div className={styles.body}>
        <div className={styles.dropzone}>
          <div className={styles.dropzoneTitle}>Drop PDF files here</div>
          <div>or click to browse</div>
        </div>
        <div className={styles.note}>
          Not wired up in this demo. Ingestion (OCR, extraction, validation) runs
          offline and the register is loaded from pre-processed results — see
          PIPELINE.md for the real flow. Dropping a file here does nothing yet.
        </div>
      </div>
    </div>
  );
}
