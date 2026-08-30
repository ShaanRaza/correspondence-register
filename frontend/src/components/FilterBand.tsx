import styles from "./FilterBand.module.css";

export interface Filters {
  dateFrom: string;
  dateTo: string;
  chainageFrom: string;
  chainageTo: string;
  direction: "" | "inward" | "outward";
  counterparty: "" | "AE" | "PD";
}

export const EMPTY_FILTERS: Filters = {
  dateFrom: "",
  dateTo: "",
  chainageFrom: "",
  chainageTo: "",
  direction: "",
  counterparty: "",
};

export function FilterBand({
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
        <span className={styles.label}>Dated</span>
        <input
          type="date"
          className={styles.input}
          value={filters.dateFrom}
          onChange={(e) => set("dateFrom", e.target.value)}
        />
        <span className={styles.dash}>–</span>
        <input
          type="date"
          className={styles.input}
          value={filters.dateTo}
          onChange={(e) => set("dateTo", e.target.value)}
        />
      </div>

      <div className={styles.group}>
        <span className={styles.label}>Chainage (m)</span>
        <input
          type="number"
          className={styles.input}
          style={{ width: 64 }}
          placeholder="from"
          value={filters.chainageFrom}
          onChange={(e) => set("chainageFrom", e.target.value)}
        />
        <span className={styles.dash}>–</span>
        <input
          type="number"
          className={styles.input}
          style={{ width: 64 }}
          placeholder="to"
          value={filters.chainageTo}
          onChange={(e) => set("chainageTo", e.target.value)}
        />
      </div>

      <div className={styles.group}>
        <span className={styles.label}>Direction</span>
        <select
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
        <span className={styles.label}>Counterparty</span>
        <select
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
