import { useMemo, useRef, useState } from "react";
import type { PackageInfo } from "../types";
import { formatDate } from "../lib/dates";
import { matchSuggestions, type Suggestion } from "../lib/suggest";
import { signOut } from "../lib/api";
import styles from "./LinearTitleBar.module.css";

export function LinearTitleBar({
  pkg,
  visibleCount,
  queryText,
  onQueryTextChange,
  onSubmitQuery,
  onOpenUpload,
  uploadStatus,
  onOpenReview,
  reviewCount,
  suggestions = [],
  onOpenDocuments,
}: {
  pkg: PackageInfo;
  visibleCount: number;
  queryText: string;
  onQueryTextChange: (text: string) => void;
  /** Optional override: a suggestion is searched immediately, and passing
   *  the text avoids reading queryText before React has applied it. */
  onSubmitQuery: (text?: string) => void;
  onOpenUpload: () => void;
  uploadStatus?: string | null;
  onOpenReview?: () => void;
  reviewCount?: number;
  /** Vocabulary drawn from this package's own letters (lib/suggest.ts). */
  suggestions?: Suggestion[];
  onOpenDocuments?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const blurTimer = useRef<number | undefined>(undefined);

  const matches = useMemo(
    () => (open ? matchSuggestions(queryText, suggestions) : []),
    [open, queryText, suggestions],
  );

  const choose = (text: string) => {
    onQueryTextChange(text);
    setOpen(false);
    setActive(-1);
    // Search the chosen term immediately -- picking a suggestion IS the query.
    onSubmitQuery(text);
  };

  return (
    <div className={styles.bar}>
      <div className={styles.left}>
        <span className={styles.packageName}>{pkg.name}</span>
        <span className={styles.meta}>{pkg.contractNo}</span>
        {pkg.periodFrom && pkg.periodTo && (
          <span className={`${styles.meta} ${styles.metaSecondary}`}>
            {formatDate(pkg.periodFrom)} – {formatDate(pkg.periodTo)}
          </span>
        )}
      </div>
      {uploadStatus && <div className={styles.uploadStatus}>{uploadStatus}</div>}
      <div className={styles.right}>
        {/* Search lives directly in the bar, always visible -- not behind a small
           button that opens a hidden panel. The author felt the query feature
           wasn't getting the prominence it deserved as "an important part"; this
           is the concrete fix, not just a bigger button. */}
        <div className={styles.searchWrap}>
          <svg className={styles.searchIcon} width="14" height="14" viewBox="0 0 16 16" fill="none">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11L14.5 14.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <input
            className={styles.searchInput}
            aria-label="Search this package's register"
            placeholder="Search correspondence — package, party, chainage, subject…"
            value={queryText}
            autoComplete="off"
            role="combobox"
            aria-expanded={matches.length > 0}
            aria-controls="search-suggestions"
            onChange={(e) => {
              onQueryTextChange(e.target.value);
              setOpen(true);
              setActive(-1);
            }}
            onFocus={() => setOpen(true)}
            // Deferred so a click on a suggestion lands before the list unmounts.
            onBlur={() => {
              blurTimer.current = window.setTimeout(() => setOpen(false), 120);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" && matches.length) {
                e.preventDefault();
                setOpen(true);
                setActive((i) => (i + 1) % matches.length);
              } else if (e.key === "ArrowUp" && matches.length) {
                e.preventDefault();
                setActive((i) => (i <= 0 ? matches.length - 1 : i - 1));
              } else if (e.key === "Enter") {
                if (active >= 0 && matches[active]) choose(matches[active].text);
                else {
                  setOpen(false);
                  onSubmitQuery();
                }
              } else if (e.key === "Escape") {
                setOpen(false);
                setActive(-1);
              }
            }}
          />
          {matches.length > 0 && (
            <ul className={styles.suggestions} id="search-suggestions" role="listbox">
              {matches.map((s, i) => (
                <li
                  key={`${s.kind}:${s.text}`}
                  role="option"
                  aria-selected={i === active}
                  className={`${styles.suggestion} ${i === active ? styles.suggestionActive : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={() => {
                    // mousedown, not click: fires before the input's blur.
                    window.clearTimeout(blurTimer.current);
                    choose(s.text);
                  }}
                >
                  <span className={styles.suggestionText}>{s.text}</span>
                  <span className={styles.suggestionKind}>{s.kind}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={styles.segment}>
          {/* These two counts measure different UNITS -- source PDFs vs. the
             individual letters extracted from them -- and shown bare side by
             side they read as if they should agree when they legitimately
             don't: one document routinely contains a covering letter plus an
             enclosure, so 17 documents can (and here does) produce 20
             letters. The unit is now named in both, not left to be inferred
             from adjacency. */}
          <span className={`${styles.segmentItem} ${styles.segmentItemActive}`}>
            {pkg.documentsIngested} of {pkg.documentsTotal} documents ingested
          </span>
          <span className={`${styles.segmentItem} ${styles.segmentItemSecondary}`}>
            {visibleCount} letters shown
          </span>
        </div>
        {onOpenReview && !!reviewCount && (
          <button className={styles.uploadButton} onClick={onOpenReview}>
            Review ({reviewCount})
          </button>
        )}
        {onOpenDocuments && (
          <button className={styles.uploadButton} onClick={onOpenDocuments}>
            Documents
          </button>
        )}
        <button className={styles.uploadButton} onClick={onOpenUpload}>
          Upload
        </button>
        <button
          className={styles.uploadButton}
          title="Sign out of this register"
          onClick={async () => {
            await signOut();
            window.location.reload();
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
