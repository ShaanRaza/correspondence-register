import type { PackageInfo } from "../types";
import { formatDate } from "../lib/dates";
import styles from "./LinearTitleBar.module.css";

export function LinearTitleBar({
  pkg,
  visibleCount,
  queryText,
  onQueryTextChange,
  onSubmitQuery,
  onOpenUpload,
  uploadStatus,
  onOpenReview,
  reviewCount,
}: {
  pkg: PackageInfo;
  visibleCount: number;
  queryText: string;
  onQueryTextChange: (text: string) => void;
  onSubmitQuery: () => void;
  onOpenUpload: () => void;
  uploadStatus?: string | null;
  onOpenReview?: () => void;
  reviewCount?: number;
}) {
  return (
    <div className={styles.bar}>
      <div className={styles.left}>
        <span className={styles.packageName}>{pkg.name}</span>
        <span className={styles.meta}>{pkg.contractNo}</span>
        {pkg.periodFrom && pkg.periodTo && (
          <span className={`${styles.meta} ${styles.metaSecondary}`}>
            {formatDate(pkg.periodFrom)} – {formatDate(pkg.periodTo)}
          </span>
        )}
      </div>
      {uploadStatus && <div className={styles.uploadStatus}>{uploadStatus}</div>}
      <div className={styles.right}>
        {/* Search lives directly in the bar, always visible -- not behind a small
           button that opens a hidden panel. The author felt the query feature
           wasn't getting the prominence it deserved as "an important part"; this
           is the concrete fix, not just a bigger button. */}
        <div className={styles.searchWrap}>
          <svg className={styles.searchIcon} width="14" height="14" viewBox="0 0 16 16" fill="none">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11L14.5 14.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <input
            className={styles.searchInput}
            aria-label="Search this package's register"
            placeholder="Search correspondence — package, party, chainage, subject…"
            value={queryText}
            onChange={(e) => onQueryTextChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSubmitQuery();
            }}
          />
        </div>
        <div className={styles.segment}>
          <span className={`${styles.segmentItem} ${styles.segmentItemActive}`}>
            {pkg.documentsIngested} of {pkg.documentsTotal} ingested
          </span>
          <span className={`${styles.segmentItem} ${styles.segmentItemSecondary}`}>
            {visibleCount} shown
          </span>
        </div>
        {onOpenReview && !!reviewCount && (
          <button className={styles.uploadButton} onClick={onOpenReview}>
            Review ({reviewCount})
          </button>
        )}
        <button className={styles.uploadButton} onClick={onOpenUpload}>
          Upload
        </button>
      </div>
    </div>
  );
}
