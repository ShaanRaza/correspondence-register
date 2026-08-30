import { useMemo, useState } from "react";
import { LinearTitleBar } from "./LinearTitleBar";
import { LinearFilterBand } from "./LinearFilterBand";
import { LinearRegister } from "./LinearRegister";
import { LinearThreadScreen } from "./LinearThreadScreen";
import { LinearQueryPanel } from "./LinearQueryPanel";
import { LinearUploadPanel } from "./LinearUploadPanel";
import tokenStyles from "./tokens.module.css";
import { EMPTY_FILTERS, type Filters } from "../components/FilterBand";
import { runQuery, type QueryResult } from "../lib/query";
import { letters, packageInfo } from "../data/fixtures";
import { parseChainageMetres } from "../lib/chainage";
import type { Letter } from "../types";

// Same view-state and filtering shape as ../App.tsx (App.tsx), by design: this is a
// visual comparison of the SAME data and behaviour, not a different product. Only
// the components, styling, and tokens differ.
type View = { screen: "register" } | { screen: "thread"; threadKey: string; selectedId: string };

// No exit-to-despatch-register link (removed on request) -- a fixed-position
// "Back to Despatch Register" pill used to float over LinearTitleBar's own
// right-aligned content and visibly overlapped it. Browser Back still works (hash
// changes push a history entry), and localhost:5173 with no hash returns to the
// shipped register directly.
export function LinearApp() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [view, setView] = useState<View>({ screen: "register" });

  const [queryText, setQueryText] = useState("");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [queryPanelOpen, setQueryPanelOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);

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

  const submitQuery = () => {
    setQueryResult(runQuery(queryText, letters, packageInfo));
    setQueryPanelOpen(true);
  };

  const overlays = (
    <>
      <LinearQueryPanel
        open={queryPanelOpen}
        onClose={() => setQueryPanelOpen(false)}
        result={queryResult}
      />
      <LinearUploadPanel open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </>
  );

  if (view.screen === "thread") {
    const threadLetters = letters.filter((l) => l.threadKey === view.threadKey);
    return (
      <div className={tokenStyles.root}>
        <LinearThreadScreen
          letters={threadLetters}
          initialSelectedId={view.selectedId}
          onBack={() => setView({ screen: "register" })}
        />
        {overlays}
      </div>
    );
  }

  return (
    <div className={tokenStyles.root}>
      <LinearTitleBar
        pkg={packageInfo}
        visibleCount={visible.length}
        queryText={queryText}
        onQueryTextChange={setQueryText}
        onSubmitQuery={submitQuery}
        onOpenUpload={() => setUploadOpen(true)}
      />
      <LinearFilterBand filters={filters} onChange={setFilters} />
      <LinearRegister letters={visible} onOpen={openThread} />
      {overlays}
    </div>
  );
}
