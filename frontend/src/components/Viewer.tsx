import type { Letter } from "../types";
import { formatDate } from "../lib/dates";
import styles from "./Viewer.module.css";

/** Placeholder for the document viewer PIPELINE.md and DESIGN.md describe: full-bleed
   scan, corner-pinned chrome, click-to-locate highlighting. No real scanned pages or
   OCR exist in this fixture-data build, so this renders a plainly-labeled stand-in
   rather than a fabricated-looking scanned letter — the structure (chrome placement,
   paper colour distinct from the app ground) is real; the "page" content is not. */
export function Viewer({ letter }: { letter: Letter }) {
  return (
    <div className={styles.pane}>
      <div className={styles.chrome}>
        <span className={styles.chromeLabel}>Page 1 of 1 · {letter.letterRef}.pdf</span>
        <span className={styles.chromeLabel}>No scanned image in this demo</span>
      </div>
      <div className={styles.page}>
        <div className={styles.pageRef}>
          {letter.letterRef} · {formatDate(letter.dated)}
        </div>
        <div className={styles.pageSubject}>{letter.subject}</div>
        <div className={styles.pageBody}>
          Extracted text would render here, with click-to-locate highlighting on any
          value selected in the chronology or register. Production renders the actual
          source page raster at full resolution — this build has no scanned documents
          or OCR output behind it yet, only the fixture register data.
        </div>
      </div>
    </div>
  );
}
