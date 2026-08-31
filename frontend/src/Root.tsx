import { Suspense, lazy, useEffect, useState } from "react";

/**
 * Hash-based switch between the two UIs. The Linear/Stripe-style UI (linear-ui/)
 * was originally built as a side-by-side comparison only, explicitly not meant to
 * replace the DESIGN.md-driven despatch register -- PRODUCT.md still says "not
 * Linear, not Notion." Per explicit direction, it's now the default; the original
 * shipped register remains reachable at #classic rather than being deleted.
 * Deliberately not React Router: two fixed views don't need a routing library.
 *
 * Lazy-loaded rather than imported statically: App.tsx imports "./styles/global.css"
 * at module scope, and a static `import App from "./App"` here would run that
 * import (and its body-level font-family/line-height rules) the instant Root.tsx
 * loads — regardless of which route is showing. Confirmed by checking computed
 * style: with a static import, `body`'s font-family read back as the shipped app's
 * Noto Sans even while the Linear route was active. React.lazy defers each
 * branch's module evaluation until it's actually rendered, so only the active
 * route's global CSS side effects ever apply.
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
      {hash === "#classic" ? <App /> : <LinearApp />}
    </Suspense>
  );
}
