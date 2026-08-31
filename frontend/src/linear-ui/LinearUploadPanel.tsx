import { useRef, useState } from "react";
import { getStoredOpenAIKey, setStoredOpenAIKey } from "../lib/api";
import styles from "./LinearUploadPanel.module.css";

export function LinearUploadPanel({
  open,
  onClose,
  onUploadFiles,
  status,
  uploading,
}: {
  open: boolean;
  onClose: () => void;
  onUploadFiles: (files: FileList) => void;
  status: string | null;
  uploading: boolean;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [apiKey, setApiKey] = useState(() => getStoredOpenAIKey());
  const [showKey, setShowKey] = useState(false);

  if (!open) return null;

  // A batch keeps running in the background even if this panel closes -- there is
  // no visible sign it's still working once dismissed, which read as "it only
  // did 1 of 14" when the rest were quietly still in flight. Closing (backdrop
  // click or the button) is disabled while a batch is active so progress can't
  // be lost sight of; minimizing was never the intent behind wanting a smaller
  // popup, staying blind to progress was.
  const handleClose = () => {
    if (!uploading) onClose();
  };

  return (
    <div className={styles.backdrop} onClick={handleClose}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <span className={styles.title}>Upload documents</span>
          <button
            className={styles.close}
            onClick={handleClose}
            disabled={uploading}
            title={uploading ? "Batch still uploading — wait for it to finish" : undefined}
          >
            {uploading ? "Uploading…" : "Close"}
          </button>
        </div>
        <div className={styles.body}>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) onUploadFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <div
            className={styles.dropzone}
            style={dragOver ? { borderColor: "var(--l-blue)", background: "var(--l-surface)" } : undefined}
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (e.dataTransfer.files.length > 0) onUploadFiles(e.dataTransfer.files);
            }}
          >
            <div className={styles.dropzoneTitle}>Drop PDF files here</div>
            <div>or click to browse</div>
          </div>

          <div className={styles.apiKeyBlock}>
            <label className={styles.apiKeyLabel} htmlFor="openai-api-key">
              OpenAI API key <span className={styles.apiKeyOptional}>(optional — uses your own quota)</span>
            </label>
            <div className={styles.apiKeyRow}>
              <input
                id="openai-api-key"
                className={styles.apiKeyInput}
                type={showKey ? "text" : "password"}
                placeholder="Leave blank to use the server's own key, if it has one"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setStoredOpenAIKey(e.target.value);
                }}
                autoComplete="off"
              />
              <button
                type="button"
                className={styles.apiKeyToggle}
                onClick={() => setShowKey((v) => !v)}
                tabIndex={-1}
              >
                {showKey ? "Hide" : "Show"}
              </button>
            </div>
            <div className={styles.apiKeyHint}>
              Stored only in this browser, sent only with your own uploads. Create a key at{" "}
              <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">
                platform.openai.com/api-keys
              </a>
              .
            </div>
          </div>

          {status && <div className={styles.note}>{status}</div>}
        </div>
      </div>
    </div>
  );
}
