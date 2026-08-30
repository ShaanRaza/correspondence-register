import { useState } from "react";
import type { Letter } from "../types";
import { Chronology } from "./Chronology";
import { Viewer } from "./Viewer";
import styles from "./ThreadScreen.module.css";

export function ThreadScreen({
  letters,
  initialSelectedId,
  onBack,
}: {
  letters: Letter[];
  initialSelectedId: string;
  onBack: () => void;
}) {
  const [selectedId, setSelectedId] = useState(initialSelectedId);
  const selected = letters.find((l) => l.id === selectedId) ?? letters[0];
  const threadKey = letters[0]?.threadKey ?? "";

  return (
    <div className={styles.screen}>
      <div className={styles.titleBlock}>
        <button className={styles.back} onClick={onBack}>
          ← Register
        </button>
        <span className={styles.subject}>Thread</span>
        <span className={styles.threadKey}>{threadKey}</span>
      </div>
      <div className={styles.split}>
        <div className={styles.chronologyPane}>
          <Chronology letters={letters} selectedId={selected.id} onSelect={setSelectedId} />
        </div>
        <div className={styles.viewerPane}>
          <Viewer letter={selected} />
        </div>
      </div>
    </div>
  );
}
