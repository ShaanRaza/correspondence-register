import { useEffect, useState } from "react";
import { fetchSession, googleSignInUrl, signIn, signUp, type Session } from "./lib/api";

/**
 * Sign-in / sign-up. Registers are private per account, so nothing renders until
 * we know whose register to show.
 *
 * Sign-up asks for an invite code because this instance is not a public service:
 * without it anyone who found the URL could create an account. The code is the
 * same APP_PASSWORD the whole instance used to share.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSession().then(setSession);
    // Surfaced by the OAuth callback when a new Google account lacked an invite
    // code -- otherwise the redirect back would look like a silent failure.
    if (new URLSearchParams(window.location.search).get("error") === "invite") {
      setError("That Google account has no register yet. Enter your invite code below, then continue with Google.");
      setMode("signup");
    }
  }, []);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = mode === "signup"
        ? await signUp(email, password, invite)
        : await signIn(email, password);
      setSession(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (session === null) return null;                 // still checking
  if (session.signedIn) return <>{children}</>;

  const label = mode === "signup" ? "Create account" : "Sign in";
  const input: React.CSSProperties = {
    width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13,
    border: "1px solid #cbd5e1", borderRadius: 6, marginBottom: 10,
  };

  return (
    <div style={{
      position: "fixed", inset: 0, display: "flex", alignItems: "center",
      justifyContent: "center", background: "#0f172a", fontFamily: "system-ui, sans-serif",
    }}>
      <div style={{ width: 340, padding: 32, background: "#fff", borderRadius: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, color: "#0f172a" }}>
          Correspondence Register
        </div>
        <div style={{ fontSize: 13, color: "#64748b", marginBottom: 16 }}>
          {mode === "signup"
            ? "Create your own register. Your documents stay private to this account."
            : "Sign in to your register."}
        </div>

        <input style={input} type="email" value={email} autoFocus autoComplete="email"
          placeholder="Email" onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !busy) submit(); }} />
        <input style={input} type="password" value={password}
          autoComplete={mode === "signup" ? "new-password" : "current-password"}
          placeholder={mode === "signup" ? "Password (min 8 characters)" : "Password"}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !busy) submit(); }} />
        {mode === "signup" && (
          <input style={input} type="text" value={invite} placeholder="Invite code"
            onChange={(e) => setInvite(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !busy) submit(); }} />
        )}

        <button onClick={submit} disabled={busy || !email || !password}
          style={{
            width: "100%", padding: "9px 12px", fontSize: 13, fontWeight: 500,
            color: "#fff", background: busy || !email || !password ? "#94a3b8" : "#4f6ef7",
            border: "none", borderRadius: 6,
            cursor: busy || !email || !password ? "default" : "pointer",
          }}>
          {busy ? "…" : label}
        </button>

        {error && <div style={{ marginTop: 10, fontSize: 12.5, color: "#dc2626" }}>{error}</div>}

        {session.googleEnabled && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "14px 0 10px" }}>
              <span style={{ flex: 1, height: 1, background: "#e2e8f0" }} />
              <span style={{ fontSize: 11.5, color: "#94a3b8" }}>or</span>
              <span style={{ flex: 1, height: 1, background: "#e2e8f0" }} />
            </div>
            <a
              href={googleSignInUrl(invite)}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                width: "100%", boxSizing: "border-box", padding: "9px 12px",
                fontSize: 13, fontWeight: 500, color: "#1f2937", textDecoration: "none",
                background: "#fff", border: "1px solid #cbd5e1", borderRadius: 6,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
                <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/>
                <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"/>
                <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z"/>
                <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"/>
              </svg>
              Continue with Google
            </a>
            {mode === "signup" && (
              <div style={{ marginTop: 8, fontSize: 11.5, color: "#94a3b8" }}>
                A new account still needs the invite code above.
              </div>
            )}
          </>
        )}

        <div style={{ marginTop: 14, fontSize: 12.5, color: "#64748b" }}>
          {mode === "signup" ? "Already have an account? " : "No account yet? "}
          <button
            onClick={() => { setMode(mode === "signup" ? "signin" : "signup"); setError(null); }}
            style={{ background: "none", border: "none", padding: 0, color: "#4f6ef7", cursor: "pointer", fontSize: 12.5 }}>
            {mode === "signup" ? "Sign in" : "Create one"}
          </button>
        </div>
      </div>
    </div>
  );
}
