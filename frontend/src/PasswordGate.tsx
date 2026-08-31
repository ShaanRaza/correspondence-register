import { useEffect, useState } from "react";
import { checkAppPassword, getStoredAppPassword, setStoredAppPassword } from "./lib/api";

type Status = "checking" | "locked" | "unlocked";

/** Wraps the whole app. A no-op when the backend has no APP_PASSWORD configured
 * (the local-dev default) -- checkAppPassword() against an ungated backend
 * always succeeds, so this never blocks local use. Only matters once deployed
 * somewhere with the gate turned on. */
export function PasswordGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("checking");
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    const stored = getStoredAppPassword();
    checkAppPassword(stored)
      .then((ok) => setStatus(ok ? "unlocked" : "locked"))
      .catch(() => setStatus("locked"));
  }, []);

  const submit = async () => {
    setChecking(true);
    setError(null);
    try {
      const ok = await checkAppPassword(input);
      if (ok) {
        setStoredAppPassword(input);
        setStatus("unlocked");
      } else {
        setError("Incorrect password.");
      }
    } catch {
      setError("Could not reach the server. Try again in a moment.");
    } finally {
      setChecking(false);
    }
  };

  if (status === "checking") return null;
  if (status === "unlocked") return <>{children}</>;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0f172a",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <div style={{ width: 320, padding: 32, background: "#fff", borderRadius: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, color: "#0f172a" }}>
          Correspondence Register
        </div>
        <div style={{ fontSize: 13, color: "#64748b", marginBottom: 16 }}>
          This instance is password-protected. Ask whoever sent you the link for it.
        </div>
        <input
          type="password"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !checking) submit();
          }}
          placeholder="Password"
          autoFocus
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "8px 12px",
            fontSize: 13,
            border: "1px solid #cbd5e1",
            borderRadius: 6,
            marginBottom: 10,
          }}
        />
        <button
          onClick={submit}
          disabled={checking || !input}
          style={{
            width: "100%",
            padding: "8px 12px",
            fontSize: 13,
            fontWeight: 500,
            color: "#fff",
            background: "#3b82f6",
            border: "none",
            borderRadius: 6,
            cursor: checking || !input ? "default" : "pointer",
            opacity: checking || !input ? 0.6 : 1,
          }}
        >
          {checking ? "Checking…" : "Enter"}
        </button>
        {error && <div style={{ marginTop: 10, fontSize: 12, color: "#b91c1c" }}>{error}</div>}
      </div>
    </div>
  );
}
