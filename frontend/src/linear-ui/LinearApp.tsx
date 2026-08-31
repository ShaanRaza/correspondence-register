import { useEffect, useMemo, useState } from "react";
import { LinearTitleBar } from "./LinearTitleBar";
import { LinearFilterBand } from "./LinearFilterBand";
import { LinearRegister } from "./LinearRegister";
import { LinearThreadScreen } from "./LinearThreadScreen";
import { LinearQueryPanel } from "./LinearQueryPanel";
import { LinearUploadPanel } from "./LinearUploadPanel";
import { LinearCitationReviewPanel } from "./LinearCitationReviewPanel";
import tokenStyles from "./tokens.module.css";
import { EMPTY_FILTERS, type Filters } from "../components/FilterBand";
import { runQuery, type QueryResult } from "../lib/query";
import { letters as fixtureLetters, packageInfo as fixturePackageInfo } from "../data/fixtures";
import { parseChainageMetres } from "../lib/chainage";
import type { Letter, PackageInfo } from "../types";
import {
  UPLOAD_PACKAGE_ID,
  describeUploadResult,
  fetchAmbiguousCitations,
  fetchLetters,
  fetchPackageInfo,
  uploadDocument,
  type AmbiguousCitation,
} from "../lib/api";

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

  // Two entirely separate data sources, never blended: see ../App.tsx's identical
  // comment -- the fixtures are a fictional package for design purposes, so a real
  // upload switches the whole register into live mode rather than mixing the two.
  const [live, setLive] = useState(false);
  const [liveLetters, setLiveLetters] = useState<Letter[]>([]);
  const [livePackageInfo, setLivePackageInfo] = useState<PackageInfo | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  // Uploading a batch is real, sequential backend work (real OCR + real Gemini
  // call per document) -- tens of seconds per file is normal, so a 14-file batch
  // can genuinely take minutes. The loop keeps running even if the panel is
  // closed, which is exactly the trap: close it (by design, or an accidental
  // backdrop click) and there's no visible sign anything is still happening,
  // reading as "it only did 1" when the rest are quietly still in flight. `uploading`
  // gates the panel's close affordances so the batch can't be dismissed blind.
  const [uploading, setUploading] = useState(false);

  const [citationReviewOpen, setCitationReviewOpen] = useState(false);
  const [ambiguousCitations, setAmbiguousCitations] = useState<AmbiguousCitation[]>([]);

  const letters = live ? liveLetters : fixtureLetters;
  const packageInfo = live && livePackageInfo ? livePackageInfo : fixturePackageInfo;

  const refreshAmbiguousCitations = () =>
    fetchAmbiguousCitations(UPLOAD_PACKAGE_ID)
      .then(setAmbiguousCitations)
      .catch(() => {});

  const refreshLive = async () => {
    const [ls, pkg] = await Promise.all([
      fetchLetters(UPLOAD_PACKAGE_ID),
      fetchPackageInfo(UPLOAD_PACKAGE_ID),
    ]);
    setLiveLetters(ls);
    setLivePackageInfo(pkg);
    await refreshAmbiguousCitations();
  };

  useEffect(() => {
    if (live) refreshLive().catch((e) => setUploadStatus(`Failed to load: ${e.message}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  // A real upload switches this session into live mode, but that's session
  // state -- reloading the page lost it, silently reverting to the fixture
  // register even though real letters exist. Check once on mount and switch
  // automatically if the live package actually has anything in it.
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
    setUploading(true);
    const list = Array.from(files);
    let succeeded = 0;
    let failed = 0;
    let lastMessage = "";
    for (let i = 0; i < list.length; i++) {
      setUploadStatus(`Uploading ${i + 1} of ${list.length}: ${list[i].name}…`);
      try {
        const result = await uploadDocument(UPLOAD_PACKAGE_ID, list[i]);
        succeeded++;
        lastMessage = describeUploadResult(list[i].name, result);
      } catch (e) {
        failed++;
        lastMessage = `${list[i].name}: failed — ${(e as Error).message}`;
      }
      setUploadStatus(lastMessage);
      await refreshLive().catch(() => {});
    }
    setUploadStatus(
      list.length === 1 ? lastMessage : `Done: ${succeeded} of ${list.length} succeeded${failed ? `, ${failed} failed` : ""}`,
    );
    setUploading(false);
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
    // The thread screen has no Upload/Query trigger of its own -- either overlay
    // left open from the register would float over it with no visible way it got
    // there, so both close on navigating in.
    setUploadOpen(false);
    setQueryPanelOpen(false);
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
      <LinearUploadPanel
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploadFiles={handleUploadFiles}
        status={uploadStatus}
        uploading={uploading}
      />
      <LinearCitationReviewPanel
        open={citationReviewOpen}
        onClose={() => setCitationReviewOpen(false)}
        citations={ambiguousCitations}
        onConfirmed={refreshLive}
      />
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
        uploadStatus={uploadStatus}
        onOpenReview={live ? () => setCitationReviewOpen(true) : undefined}
        reviewCount={ambiguousCitations.length}
      />
      <LinearFilterBand filters={filters} onChange={setFilters} />
      <LinearRegister letters={visible} onOpen={openThread} />
      {overlays}
    </div>
  );
}
