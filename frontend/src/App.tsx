import { useMemo, useState } from "react";
import { TitleBlock } from "./components/TitleBlock";
import { FilterBand, EMPTY_FILTERS, type Filters } from "./components/FilterBand";
import { Register } from "./components/Register";
import { letters, packageInfo } from "./data/fixtures";
import { parseChainageMetres } from "./lib/chainage";
import "./styles/global.css";

function App() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);

  const visible = useMemo(() => {
    return letters.filter((l) => {
      if (filters.dateFrom && l.dated < filters.dateFrom) return false;
      if (filters.dateTo && l.dated > filters.dateTo) return false;

      if (filters.chainageFrom || filters.chainageTo) {
        const m = parseChainageMetres(l.chainage);
        if (m == null) return false;
        if (filters.chainageFrom && m < Number(filters.chainageFrom)) return false;
        if (filters.chainageTo && m > Number(filters.chainageTo)) return false;
      }

      if (filters.direction && l.direction !== filters.direction) return false;

      if (filters.counterparty) {
        const counterparties = [l.from, l.to];
        if (!counterparties.includes(filters.counterparty)) return false;
      }

      return true;
    });
  }, [filters]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <TitleBlock pkg={packageInfo} visibleCount={visible.length} />
      <FilterBand filters={filters} onChange={setFilters} />
      <Register letters={visible} />
    </div>
  );
}

export default App;
