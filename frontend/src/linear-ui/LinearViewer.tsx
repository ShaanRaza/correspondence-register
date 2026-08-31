import { useEffect, useState } from "react";
import type { ExtractedFieldProvenance, Letter } from "../types";
import { formatDate } from "../lib/dates";
import { fetchLetterFields, fetchRasterObjectUrl } from "../lib/api";
import styles from "./LinearViewer.module.css";

const FIELD_LABELS: Record<string, string> = {
  letter_ref: "Letter ref",
  dated: "Date",
  received: "Received",
  from_party: "From",
  to_party: "To",
  subject: "Subject",
  chainage: "Chainage",
  clause: "Clause",
  cited_ref: "Cited ref",
};

function fieldKeyOf(f: ExtractedFieldProvenance): string {
  return `${f.fieldKey}:${f.fieldIndex}`;
}

// Identifier fields (reference numbers) have no legitimate "normalized" form --
// the model's separate "value" field for these has no validation guarantee and
// real data showed it silently dropping/inserting characters even when the
// verbatim (the text S4 actually proved exists in the source) was correct.
// Dates and chainage genuinely benefit from normalization, so those keep
// showing "value" first.
const VERBATIM_FIRST_FIELDS = new Set(["letter_ref", "cited_ref"]);

function displayValue(f: ExtractedFieldProvenance): string {
  if (VERBATIM_FIRST_FIELDS.has(f.fieldKey)) {
    return f.valueVerbatim ?? f.valueText ?? "—";
  }
  return f.valueText ?? f.valueVerbatim ?? "—";
}

/* Live letters (real uploads) render the actual scanned page raster with the
   real extracted-field bounding boxes overlaid -- this is PIPELINE.md's
   click-to-locate citation feature, backed by data the pipeline already
   captured (S5 provenance mapping) but never had a UI wired to it. Fixture
   letters have no real document behind them, so they keep the honest
   placeholder below unchanged. */
export function LinearViewer({ letter }: { letter: Letter }) {
  const [fields, setFields] = useState<ExtractedFieldProvenance[] | null>(null);
  const [activeField, setActiveField] = useState<string | null>(null);
  const [page, setPage] = useState<number>(letter.pageFrom ?? 1);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  useEffect(() => {
    setFields(null);
    setActiveField(null);
    setPage(letter.pageFrom ?? 1);
    setLoadError(null);
    if (!letter.documentSha256) return;
    fetchLetterFields(letter.id)
      .then(setFields)
      .catch((e) => setLoadError((e as Error).message));
  }, [letter.id, letter.documentSha256, letter.pageFrom]);

  // The image needs the app-password header, which a plain <img src> can't
  // send -- fetched as a blob instead and swapped in as an object URL. Revoked
  // on every change so switching pages/letters doesn't leak memory.
  useEffect(() => {
    if (!letter.documentSha256) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchRasterObjectUrl(letter.documentSha256, page)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setImageUrl(url);
      })
      .catch((e) => setLoadError((e as Error).message));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [letter.documentSha256, page]);

  if (!letter.documentSha256) {
    return (
      <div className={styles.pane}>
        <div className={styles.toolbar}>
          <div className={styles.toolbarLeft}>
            <span>Page 1 of 1</span>
            <span>·</span>
            <span>{letter.letterRef}.pdf</span>
          </div>
        </div>
        <div className={styles.pageArea}>
          <div className={styles.paper}>
            <div className={styles.pageRef}>
              {letter.letterRef} · {formatDate(letter.dated)}
            </div>
            <div className={styles.pageSubject}>{letter.subject}</div>
            <div className={styles.pageBody}>
              Extracted text would render here, with click-to-locate highlighting on any
              value selected in the timeline or register.
            </div>
            <div className={styles.placeholderNote}>
              No scanned image in this demo — production renders the real source page
              raster.
            </div>
          </div>
        </div>
      </div>
    );
  }

  const pageFrom = letter.pageFrom ?? 1;
  const pageTo = letter.pageTo ?? pageFrom;
  const highlightsOnThisPage = (fields ?? []).filter((f) => f.pageNo === page && f.bbox);

  return (
    <div className={styles.pane}>
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <span>
            Page {page} of {pageTo}
          </span>
          <span>·</span>
          <span>{letter.letterRef}.pdf</span>
        </div>
        {pageTo > pageFrom && (
          <div style={{ display: "flex", gap: 6 }}>
            <button
              className={styles.iconButton}
              aria-label="Previous page"
              disabled={page <= pageFrom}
              onClick={() => setPage((p) => Math.max(pageFrom, p - 1))}
            >
              ‹
            </button>
            <button
              className={styles.iconButton}
              aria-label="Next page"
              disabled={page >= pageTo}
              onClick={() => setPage((p) => Math.min(pageTo, p + 1))}
            >
              ›
            </button>
          </div>
        )}
      </div>
      <div className={styles.pageArea}>
        <div className={styles.imageWrap}>
          {imageUrl && (
            <img
              key={page}
              src={imageUrl}
              alt={`Scanned page ${page} of ${letter.letterRef}`}
              className={styles.pageImage}
              onError={() => setLoadError("Could not load the source page image.")}
            />
          )}
          {highlightsOnThisPage.map((f) => {
            const u = f.bbox!.union;
            const active = activeField === fieldKeyOf(f);
            return (
              <div
                key={fieldKeyOf(f)}
                className={`${styles.highlight} ${active ? styles.highlightActive : ""}`}
                style={{ left: `${u.x * 100}%`, top: `${u.y * 100}%`, width: `${u.w * 100}%`, height: `${u.h * 100}%` }}
              />
            );
          })}
        </div>
        {loadError && <div className={styles.placeholderNote}>{loadError}</div>}
      </div>
      <div className={styles.fieldsList}>
        {fields === null && !loadError && <div className={styles.fieldsLoading}>Loading sources…</div>}
        {(fields ?? []).map((f) => (
          <button
            key={fieldKeyOf(f)}
            className={`${styles.fieldRow} ${activeField === fieldKeyOf(f) ? styles.fieldRowActive : ""}`}
            onClick={() => {
              if (f.pageNo) setPage(f.pageNo);
              setActiveField(fieldKeyOf(f));
            }}
            disabled={!f.bbox}
            title={f.validation === "normalized_exact" ? "Matched after whitespace/Unicode normalization" : undefined}
          >
            <span className={styles.fieldKey}>{FIELD_LABELS[f.fieldKey] ?? f.fieldKey}</span>
            <span className={styles.fieldValue}>{displayValue(f)}</span>
            {f.validation === "unresolved" && <span className={styles.unresolvedBadge}>not located in source</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
