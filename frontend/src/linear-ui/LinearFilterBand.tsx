import { EMPTY_FILTERS, type Filters } from "../components/FilterBand";
import styles from "./LinearFilterBand.module.css";

// Reuses the same Filters type and EMPTY_FILTERS constant as the shipped filter
// band — same state shape, same filtering logic in LinearApp — only the markup and
// styling differ, per the request to keep bindings and logic intact.
export function LinearFilterBand({
  filters,
  onChange,
}: {
  filters: Filters;
  onChange: (next: Filters) => void;
}) {
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    onChange({ ...filters, [key]: value });

  const isEmpty = JSON.stringify(filters) === JSON.stringify(EMPTY_FILTERS);

  return (
    <div className={styles.band}>
      <div className={styles.group}>
        <label className={styles.label} htmlFor="l-date-from">
          Dated
        </label>
        <input
          id="l-date-from"
          type="date"
          className={styles.input}
          value={filters.dateFrom}
          onChange={(e) => set("dateFrom", e.target.value)}
        />
        <span className={styles.dash}>–</span>
        <input
          type="date"
          className={styles.input}
          aria-label="Dated to"
          value={filters.dateTo}
          onChange={(e) => set("dateTo", e.target.value)}
        />
      </div>

      <div className={styles.group}>
        <label className={styles.label} htmlFor="l-chainage-from">
          Chainage (m)
        </label>
        <input
          id="l-chainage-from"
          type="number"
          className={styles.input}
          style={{ width: 72 }}
          placeholder="from"
          value={filters.chainageFrom}
          onChange={(e) => set("chainageFrom", e.target.value)}
        />
        <span className={styles.dash}>–</span>
        <input
          type="number"
          className={styles.input}
          style={{ width: 72 }}
          placeholder="to"
          aria-label="Chainage to"
          value={filters.chainageTo}
          onChange={(e) => set("chainageTo", e.target.value)}
        />
      </div>

      <div className={styles.group}>
        <label className={styles.label} htmlFor="l-direction">
          Direction
        </label>
        <select
          id="l-direction"
          className={styles.select}
          value={filters.direction}
          onChange={(e) => set("direction", e.target.value as Filters["direction"])}
        >
          <option value="">All</option>
          <option value="outward">Outward</option>
          <option value="inward">Inward</option>
        </select>
      </div>

      <div className={styles.group}>
        <label className={styles.label} htmlFor="l-counterparty">
          Counterparty
        </label>
        <select
          id="l-counterparty"
          className={styles.select}
          value={filters.counterparty}
          onChange={(e) => set("counterparty", e.target.value as Filters["counterparty"])}
        >
          <option value="">All</option>
          <option value="AE">AE</option>
          <option value="PD">PD</option>
        </select>
      </div>

      {!isEmpty && (
        <button className={styles.clear} onClick={() => onChange(EMPTY_FILTERS)}>
          Clear filters
        </button>
      )}
    </div>
  );
}
