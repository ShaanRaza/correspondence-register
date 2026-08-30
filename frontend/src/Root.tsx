import { Suspense, lazy, useEffect, useState } from "react";

/**
 * Hash-based switch between the shipped despatch-register UI (default) and the
 * Linear/Stripe-style comparison (#linear) requested for exploration only — per
 * the author's explicit choice not to replace the shipped identity or touch
 * PRODUCT.md/DESIGN.md. Deliberately not React Router: two fixed views don't need
 * a routing library, and this stays a pure addition with zero changes to App.tsx.
 *
 * Lazy-loaded rather than imported statically: App.tsx imports "./styles/global.css"
 * at module scope, and a static `import App from "./App"` here would run that
 * import (and its body-level font-family/line-height rules) the instant Root.tsx
 * loads — regardless of which route is showing. Confirmed by checking computed
 * style: with a static import, `body`'s font-family read back as the shipped app's
 * Noto Sans even while #linear was active. React.lazy defers each branch's module
 * evaluation until it's actually rendered, so only the active route's global CSS
 * side effects ever apply.
 */
const App = lazy(() => import("./App"));
const LinearApp = lazy(() => import("./linear-ui/LinearApp").then((m) => ({ default: m.LinearApp })));

export default function Root() {
  const [hash, setHash] = useState(window.location.hash);

  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <Suspense fallback={null}>
      {hash === "#linear" ? (
        <LinearApp onExit={() => (window.location.hash = "")} />
      ) : (
        <App />
      )}
    </Suspense>
  );
}
