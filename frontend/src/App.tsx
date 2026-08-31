import { useEffect, useMemo, useState } from "react";
import { TitleBlock } from "./components/TitleBlock";
import { FilterBand, EMPTY_FILTERS, type Filters } from "./components/FilterBand";
import { Register } from "./components/Register";
import { ThreadScreen } from "./components/ThreadScreen";
import { QueryPanel } from "./components/QueryPanel";
import { letters as fixtureLetters, packageInfo as fixturePackageInfo } from "./data/fixtures";
import { parseChainageMetres } from "./lib/chainage";
import type { Letter, PackageInfo } from "./types";
import { UPLOAD_PACKAGE_ID, describeUploadResult, fetchLetters, fetchPackageInfo, uploadDocument } from "./lib/api";
import "./styles/global.css";

type View = { screen: "register" } | { screen: "thread"; threadKey: string; selectedId: string };

function App() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [view, setView] = useState<View>({ screen: "register" });
  const [queryOpen, setQueryOpen] = useState(false);

  // Two entirely separate data sources, never blended: the design fixtures (a
  // fictional package, for demo/screenshot purposes) versus real letters ingested
  // from documents actually uploaded through this screen. Uploading a real document
  // switches the whole register into live mode for the rest of the session --
  // mixing fabricated sample letters with real evidentiary ones would misrepresent
  // what's on screen.
  const [live, setLive] = useState(false);
  const [liveLetters, setLiveLetters] = useState<Letter[]>([]);
  const [livePackageInfo, setLivePackageInfo] = useState<PackageInfo | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);

  const letters = live ? liveLetters : fixtureLetters;
  const packageInfo = live && livePackageInfo ? livePackageInfo : fixturePackageInfo;

  const refreshLive = async () => {
    const [ls, pkg] = await Promise.all([
      fetchLetters(UPLOAD_PACKAGE_ID),
      fetchPackageInfo(UPLOAD_PACKAGE_ID),
    ]);
    setLiveLetters(ls);
    setLivePackageInfo(pkg);
  };

  useEffect(() => {
    if (live) refreshLive().catch((e) => setUploadStatus(`Failed to load: ${e.message}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  // See LinearApp.tsx's identical check: live mode is session state, so a
  // reload silently reverted to fixtures even with real letters on the server.
  useEffect(() => {
    if (live) return;
    fetchLetters(UPLOAD_PACKAGE_ID)
      .then((ls) => {
        if (ls.length > 0) setLive(true);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleUploadFiles = async (files: FileList) => {
    setLive(true);
    const list = Array.from(files);
    for (let i = 0; i < list.length; i++) {
      setUploadStatus(`Uploading ${i + 1} of ${list.length}: ${list[i].name}…`);
      try {
        const result = await uploadDocument(UPLOAD_PACKAGE_ID, list[i]);
        setUploadStatus(describeUploadResult(list[i].name, result));
      } catch (e) {
        setUploadStatus(`${list[i].name}: failed — ${(e as Error).message}`);
      }
      await refreshLive().catch(() => {});
    }
    window.setTimeout(() => setUploadStatus(null), 4000);
  };

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
  }, [filters, letters]);

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
          onUploadFiles={handleUploadFiles}
          uploadStatus={uploadStatus}
        />
        <FilterBand filters={filters} onChange={setFilters} />
        <Register letters={visible} onOpen={openThread} />
      </div>
      {queryPanel}
      {/* Exploratory comparison only, per the author's explicit "don't commit yet"
          decision — a Linear/Stripe-style alternative to look at side by side, not a
          change to this screen. Deliberately minimal so it reads as a dev/meta
          control, not a product feature. */}
      <a
        href="#linear"
        style={{
          position: "fixed",
          bottom: 12,
          left: 16,
          fontFamily: "var(--font-text)",
          fontSize: 11,
          color: "var(--ink-3)",
          textDecoration: "underline",
          textUnderlineOffset: 2,
        }}
      >
        Compare: Linear-style UI →
      </a>
    </>
  );
}

export default App;
