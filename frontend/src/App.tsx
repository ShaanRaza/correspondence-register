import { useMemo, useState } from "react";
import { TitleBlock } from "./components/TitleBlock";
import { FilterBand, EMPTY_FILTERS, type Filters } from "./components/FilterBand";
import { Register } from "./components/Register";
import { ThreadScreen } from "./components/ThreadScreen";
import { QueryPanel } from "./components/QueryPanel";
import { letters, packageInfo } from "./data/fixtures";
import { parseChainageMetres } from "./lib/chainage";
import type { Letter } from "./types";
import "./styles/global.css";

type View = { screen: "register" } | { screen: "thread"; threadKey: string; selectedId: string };

function App() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [view, setView] = useState<View>({ screen: "register" });
  const [queryOpen, setQueryOpen] = useState(false);

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

  const openThread = (letter: Letter) => {
    setView({ screen: "thread", threadKey: letter.threadKey, selectedId: letter.id });
  };

  const queryPanel = (
    <QueryPanel
      open={queryOpen}
      onClose={() => setQueryOpen(false)}
      letters={letters}
      pkg={packageInfo}
    />
  );

  if (view.screen === "thread") {
    const threadLetters = letters.filter((l) => l.threadKey === view.threadKey);
    return (
      <>
        <ThreadScreen
          letters={threadLetters}
          initialSelectedId={view.selectedId}
          onBack={() => setView({ screen: "register" })}
          onOpenQuery={() => setQueryOpen(true)}
        />
        {queryPanel}
      </>
    );
  }

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <TitleBlock
          pkg={packageInfo}
          visibleCount={visible.length}
          onOpenQuery={() => setQueryOpen(true)}
        />
        <FilterBand filters={filters} onChange={setFilters} />
        <Register letters={visible} onOpen={openThread} />
      </div>
      {queryPanel}
    </>
  );
}

export default App;
