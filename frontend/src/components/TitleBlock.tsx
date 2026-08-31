import { useRef } from "react";
import type { PackageInfo } from "../types";
import { formatDate } from "../lib/dates";
import styles from "./TitleBlock.module.css";
import queryStyles from "./QueryPanel.module.css";

export function TitleBlock({
  pkg,
  visibleCount,
  onOpenQuery,
  onUploadFiles,
  uploadStatus,
}: {
  pkg: PackageInfo;
  visibleCount: number;
  onOpenQuery: () => void;
  onUploadFiles: (files: FileList) => void;
  uploadStatus: string | null;
}) {
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <div className={styles.block}>
      <div className={styles.left}>
        <span className={styles.packageName}>{pkg.name}</span>
        <span className={styles.contractNo}>{pkg.contractNo}</span>
        {pkg.periodFrom && pkg.periodTo && (
          <span className={styles.period}>
            {formatDate(pkg.periodFrom)} – {formatDate(pkg.periodTo)}
          </span>
        )}
      </div>
      <div className={styles.right}>
        <div className={styles.completeness}>
          {pkg.documentsIngested} of {pkg.documentsTotal} ingested
          <span className={styles.fraction}>{visibleCount} shown</span>
        </div>
        {uploadStatus && (
          <span className={styles.contractNo} aria-live="polite">
            {uploadStatus}
          </span>
        )}
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf"
          multiple
          style={{ display: "none" }}
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) onUploadFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button className={queryStyles.inlineTrigger} onClick={() => fileInput.current?.click()}>
          Upload
        </button>
        <button className={queryStyles.inlineTrigger} onClick={onOpenQuery}>
          Query
        </button>
      </div>
    </div>
  );
}
