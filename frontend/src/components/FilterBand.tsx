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
        <label className={styles.label} htmlFor="filter-date-from">
          Dated
        </label>
        <input
          id="filter-date-from"
          type="date"
          className={styles.input}
          value={filters.dateFrom}
          onChange={(e) => set("dateFrom", e.target.value)}
        />
        <span className={styles.dash} aria-hidden="true">
          –
        </span>
        <label className="visually-hidden" htmlFor="filter-date-to">
          Dated to
        </label>
        <input
          id="filter-date-to"
          type="date"
          className={styles.input}
          value={filters.dateTo}
          onChange={(e) => set("dateTo", e.target.value)}
        />
      </div>

      <div className={styles.group}>
        <label className={styles.label} htmlFor="filter-chainage-from">
          Chainage (m)
        </label>
        <input
          id="filter-chainage-from"
          type="number"
          className={styles.input}
          style={{ width: 64 }}
          placeholder="from"
          value={filters.chainageFrom}
          onChange={(e) => set("chainageFrom", e.target.value)}
        />
        <span className={styles.dash} aria-hidden="true">
          –
        </span>
        <label className="visually-hidden" htmlFor="filter-chainage-to">
          Chainage to
        </label>
        <input
          id="filter-chainage-to"
          type="number"
          className={styles.input}
          style={{ width: 64 }}
          placeholder="to"
          value={filters.chainageTo}
          onChange={(e) => set("chainageTo", e.target.value)}
        />
      </div>

      <div className={styles.group}>
        <label className={styles.label} htmlFor="filter-direction">
          Direction
        </label>
        <select
          id="filter-direction"
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
        <label className={styles.label} htmlFor="filter-counterparty">
          Counterparty
        </label>
        <select
          id="filter-counterparty"
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
