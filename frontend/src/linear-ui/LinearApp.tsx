import { useMemo, useState } from "react";
import { LinearTitleBar } from "./LinearTitleBar";
import { LinearFilterBand } from "./LinearFilterBand";
import { LinearRegister } from "./LinearRegister";
import { LinearThreadScreen } from "./LinearThreadScreen";
import { LinearQueryPanel } from "./LinearQueryPanel";
import tokenStyles from "./tokens.module.css";
import { EMPTY_FILTERS, type Filters } from "../components/FilterBand";
import { letters, packageInfo } from "../data/fixtures";
import { parseChainageMetres } from "../lib/chainage";
import type { Letter } from "../types";

// Same view-state and filtering shape as ../App.tsx (App.tsx), by design: this is a
// visual comparison of the SAME data and behaviour, not a different product. Only
// the components, styling, and tokens differ.
type View = { screen: "register" } | { screen: "thread"; threadKey: string; selectedId: string };

export function LinearApp({ onExit }: { onExit: () => void }) {
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
    <LinearQueryPanel
      open={queryOpen}
      onClose={() => setQueryOpen(false)}
      letters={letters}
      pkg={packageInfo}
    />
  );

  const exitLink = (
    <button className={tokenStyles.compareLink} onClick={onExit}>
      ← Back to Despatch Register
    </button>
  );

  if (view.screen === "thread") {
    const threadLetters = letters.filter((l) => l.threadKey === view.threadKey);
    return (
      <div className={tokenStyles.root}>
        {exitLink}
        <LinearThreadScreen
          letters={threadLetters}
          initialSelectedId={view.selectedId}
          onBack={() => setView({ screen: "register" })}
        />
        {queryPanel}
      </div>
    );
  }

  return (
    <div className={tokenStyles.root}>
      {exitLink}
      <LinearTitleBar
        pkg={packageInfo}
        visibleCount={visible.length}
        onOpenQuery={() => setQueryOpen(true)}
      />
      <LinearFilterBand filters={filters} onChange={setFilters} />
      <LinearRegister letters={visible} onOpen={openThread} />
      {queryPanel}
    </div>
  );
}
