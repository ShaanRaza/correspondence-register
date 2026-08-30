import type { PackageInfo } from "../types";
import { formatDate } from "../lib/dates";
import styles from "./TitleBlock.module.css";
import queryStyles from "./QueryPanel.module.css";

export function TitleBlock({
  pkg,
  visibleCount,
  onOpenQuery,
}: {
  pkg: PackageInfo;
  visibleCount: number;
  onOpenQuery: () => void;
}) {
  return (
    <div className={styles.block}>
      <div className={styles.left}>
        <span className={styles.packageName}>{pkg.name}</span>
        <span className={styles.contractNo}>{pkg.contractNo}</span>
        <span className={styles.period}>
          {formatDate(pkg.periodFrom)} – {formatDate(pkg.periodTo)}
        </span>
      </div>
      <div className={styles.right}>
        <div className={styles.completeness}>
          {pkg.documentsIngested} of {pkg.documentsTotal} ingested
          <span className={styles.fraction}>{visibleCount} shown</span>
        </div>
        <button className={queryStyles.inlineTrigger} onClick={onOpenQuery}>
          Query
        </button>
      </div>
    </div>
  );
}
