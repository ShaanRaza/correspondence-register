import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * The single most important thing this component does: turn "nothing on
 * screen" into "an actual error message on screen".
 *
 * This app had NO error boundary and NO global error handlers at all. React's
 * default behavior on an uncaught render error is to unmount the ENTIRE tree
 * -- silently, with nothing left in the DOM. That is indistinguishable from a
 * server outage, a caching bug, or anything else, and it is what "I see the
 * content, then just headers, then a blank white screen" almost certainly
 * was: something threw partway through a re-render (react unmounts from the
 * point of the throw upward, which is why HIGHER content like a header can
 * briefly outlive lower content before the whole tree finally goes), and
 * there was no way for anyone -- including whoever built this -- to see WHAT
 * threw, because nothing was ever written down anywhere visible.
 *
 * This does not fix whatever the underlying bug is. It makes the NEXT
 * occurrence diagnosable in one screenshot instead of requiring a live
 * reproduction, which is the actual blocker right now.
 */
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Also visible without a debugger attached -- Safari's own Console.
    console.error("[ErrorBoundary] render error:", error, info.componentStack);
  }

  componentDidMount() {
    // React's boundary only catches errors DURING RENDER. A throw inside an
    // event handler, a setTimeout, or an async continuation (all real
    // possibilities here -- e.g. the upload loop, the search dropdown's
    // timers) bypasses it entirely and would otherwise vanish just as
    // silently. These two listeners are the safety net for everything else.
    window.addEventListener("error", this.onWindowError);
    window.addEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  componentWillUnmount() {
    window.removeEventListener("error", this.onWindowError);
    window.removeEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  private onWindowError = (e: ErrorEvent) => {
    console.error("[window.onerror]", e.error ?? e.message);
    this.setState({ error: e.error instanceof Error ? e.error : new Error(String(e.message)) });
  };

  private onUnhandledRejection = (e: PromiseRejectionEvent) => {
    console.error("[unhandledrejection]", e.reason);
    this.setState({
      error: e.reason instanceof Error ? e.reason : new Error(String(e.reason)),
    });
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{
        position: "fixed", inset: 0, display: "flex", alignItems: "center",
        justifyContent: "center", background: "#0f172a", fontFamily: "system-ui, sans-serif",
        padding: 24,
      }}>
        <div style={{ width: "min(560px, 100%)", padding: 28, background: "#fff", borderRadius: 12 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#0f172a", marginBottom: 6 }}>
            Something went wrong
          </div>
          <div style={{ fontSize: 13, color: "#64748b", marginBottom: 16 }}>
            The page hit an unexpected error and stopped rather than showing something
            incorrect. Reloading usually recovers it; if it keeps happening, the message below
            says exactly what failed.
          </div>
          <pre style={{
            fontSize: 12, color: "#dc2626", background: "#fef2f2", padding: 12,
            borderRadius: 6, overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word",
            marginBottom: 16,
          }}>
            {this.state.error.message}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "9px 16px", fontSize: 13, fontWeight: 500, color: "#fff",
              background: "#4f6ef7", border: "none", borderRadius: 6, cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
