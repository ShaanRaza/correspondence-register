import { useState } from "react";
import type { Letter } from "../types";
import { LinearTimeline } from "./LinearTimeline";
import { LinearViewer } from "./LinearViewer";
import styles from "./LinearThreadScreen.module.css";

export function LinearThreadScreen({
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
      <div className={styles.header}>
        <button className={styles.back} onClick={onBack}>
          ← Register
        </button>
        <span className={styles.title}>Thread</span>
        <span className={styles.threadKey}>{threadKey}</span>
      </div>
      <div className={styles.split}>
        <div className={styles.timelinePane}>
          <LinearTimeline letters={letters} selectedId={selected.id} onSelect={setSelectedId} />
        </div>
        <div className={styles.viewerPane}>
          <LinearViewer letter={selected} />
        </div>
      </div>
    </div>
  );
}
