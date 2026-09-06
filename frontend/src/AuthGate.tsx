import { useEffect, useState } from "react";
import { fetchSession, googleSignInUrl, type Session } from "./lib/api";

/**
 * Sign in with Google. Nothing else to type.
 *
 * There is no password here on purpose: a password is one more secret for the
 * user to manage and for this app to store, and Google already proves the same
 * thing better. The account IS the verified Google email.
 *
 * A NEW register still has to be invited, or anyone with a Google account could
 * create one on this instance and spend the owner's model credits. The invite
 * travels in the link (`?invite=CODE`) rather than being typed, so being invited
 * means clicking one link and then one button. Signing IN to an existing account
 * never needs it.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [invite, setInvite] = useState("");
  const [needsInvite, setNeedsInvite] = useState(false);

  useEffect(() => {
    fetchSession().then((s) => {
      setSession(s);
      // Drop ?invite / ?error once they have served their purpose, so the URL
      // in the address bar (and anything the user bookmarks or shares) is the
      // plain app rather than a link carrying an invite code around.
      if (s.signedIn && window.location.search) {
        window.history.replaceState({}, "", window.location.pathname);
      }
    });
    const params = new URLSearchParams(window.location.search);
    const fromLink = params.get("invite");
    if (fromLink) setInvite(fromLink);
    // Set by the OAuth callback when a new account arrived without an invite.
    if (params.get("error") === "invite") setNeedsInvite(true);

    // Coming BACK to this page from history does not re-run the app: browsers
    // restore the previous render from the back/forward cache, which showed the
    // sign-in screen again to someone who is already signed in. Re-checking the
    // session on restore is what makes "signed in stays signed in".
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) fetchSession().then(setSession);
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  if (session === null) {
    // A visible, non-blank state while checking (bounded to ~8s by
    // fetchSession's own timeout -- this can no longer hang indefinitely).
    // Truly blank here reads identically to "broken" with nothing to tell
    // the two apart.
    return (
      <div style={{
        position: "fixed", inset: 0, display: "flex", alignItems: "center",
        justifyContent: "center", background: "#0f172a", color: "#94a3b8",
        fontFamily: "system-ui, sans-serif", fontSize: 13,
      }}>
        Loading…
      </div>
    );
  }
  if (session.signedIn) return <>{children}</>;

  return (
    <div style={{
      position: "fixed", inset: 0, display: "flex", alignItems: "center",
      justifyContent: "center", background: "#0f172a", fontFamily: "system-ui, sans-serif",
    }}>
      <div style={{ width: 340, padding: 32, background: "#fff", borderRadius: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, color: "#0f172a" }}>
          Correspondence Register
        </div>
        <div style={{ fontSize: 13, color: "#64748b", marginBottom: 18 }}>
          Sign in with your Google account. Your register stays private to it.
        </div>

        {session.googleEnabled ? (
          <a
            href={googleSignInUrl(invite)}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              width: "100%", boxSizing: "border-box", padding: "10px 12px",
              fontSize: 13.5, fontWeight: 500, color: "#1f2937", textDecoration: "none",
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
        ) : (
          <div style={{ fontSize: 12.5, color: "#dc2626" }}>
            Google sign-in is not configured on this server yet.
          </div>
        )}

        {/* Only appears if an invite was actually required and missing, so the
            common path shows a single button and nothing else. */}
        {needsInvite && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 12.5, color: "#dc2626", marginBottom: 8 }}>
              This Google account doesn't have a register yet. Paste the invite code to create one.
            </div>
            <input
              type="text"
              value={invite}
              placeholder="Invite code"
              onChange={(e) => setInvite(e.target.value)}
              style={{
                width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13,
                border: "1px solid #cbd5e1", borderRadius: 6,
              }}
            />
            <div style={{ marginTop: 8, fontSize: 11.5, color: "#94a3b8" }}>
              Then press Continue with Google again.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
