import type { Letter } from "../types";
import { formatDate } from "../lib/dates";
import styles from "./LinearViewer.module.css";

/* Same honest placeholder as the shipped Viewer: no real scanned pages or OCR exist
   behind this fixture-data build. The floating paper card is real chrome; the "page"
   content inside it is clearly marked as a stand-in, not dressed up as a real scan. */
export function LinearViewer({ letter }: { letter: Letter }) {
  return (
    <div className={styles.pane}>
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <span>Page 1 of 1</span>
          <span>·</span>
          <span>{letter.letterRef}.pdf</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button className={styles.iconButton} aria-label="Zoom out">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.3" />
              <path d="M11 11L15 15" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <path d="M4.5 7H9.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
          </button>
          <button className={styles.iconButton} aria-label="Zoom in">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.3" />
              <path d="M11 11L15 15" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <path d="M7 4.5V9.5M4.5 7H9.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
          </button>
          <button className={styles.iconButton} aria-label="Rotate page">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path
                d="M13 8A5 5 0 1 1 11 4"
                stroke="currentColor"
                strokeWidth="1.3"
                strokeLinecap="round"
              />
              <path d="M13 2V5H10" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
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
