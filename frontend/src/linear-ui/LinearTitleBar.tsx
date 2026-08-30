import type { PackageInfo } from "../types";
import { formatDate } from "../lib/dates";
import styles from "./LinearTitleBar.module.css";

export function LinearTitleBar({
  pkg,
  visibleCount,
  onOpenQuery,
}: {
  pkg: PackageInfo;
  visibleCount: number;
  onOpenQuery: () => void;
}) {
  return (
    <div className={styles.bar}>
      <div className={styles.left}>
        <span className={styles.packageName}>{pkg.name}</span>
        <span className={styles.meta}>{pkg.contractNo}</span>
        <span className={styles.meta}>
          {formatDate(pkg.periodFrom)} – {formatDate(pkg.periodTo)}
        </span>
      </div>
      <div className={styles.right}>
        <div className={styles.segment}>
          <span className={`${styles.segmentItem} ${styles.segmentItemActive}`}>
            {pkg.documentsIngested} of {pkg.documentsTotal} ingested
          </span>
          <span className={styles.segmentItem}>{visibleCount} shown</span>
        </div>
        <button className={styles.queryButton} onClick={onOpenQuery}>
          Query
        </button>
      </div>
    </div>
  );
}
