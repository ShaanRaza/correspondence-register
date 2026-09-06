import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted fonts, per DESIGN.md — Noto Sans (Latin + Devanagari, this product's
// bilingual content on one line), Noto Sans Mono (every transcribable value),
// Archivo (column heads and labels only).
import "@fontsource/noto-sans/400.css";
import "@fontsource/noto-sans/500.css";
import "@fontsource/noto-sans/600.css";
import "@fontsource/noto-sans/devanagari-400.css";
import "@fontsource/noto-sans/devanagari-500.css";
import "@fontsource/noto-sans/devanagari-600.css";
import "@fontsource/noto-sans-mono/400.css";
import "@fontsource/noto-sans-mono/500.css";
import "@fontsource/archivo/500.css";
import "@fontsource/archivo/600.css";

// IBM Plex Sans, for the exploratory Linear/Stripe-style comparison UI only (#linear
// route). The shipped despatch register never uses it. Replaced Inter after the
// author flagged the comparison as reading "AI-generated" — Inter plus a slate
// palette and pill badges is the single most recognizable generic-SaaS-template
// signature at this point; Plex is a genuine enterprise/dev-tool typeface instead
// of the reflexive default.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";

import Root from "./Root.tsx";
import { AuthGate } from "./AuthGate.tsx";
import { ErrorBoundary } from "./ErrorBoundary.tsx";
import { bootstrapConfig } from "./lib/api";

// Render immediately. Gating the FIRST render on a network request (as this
// once did) meant one stalled connection left the page permanently blank --
// React never even mounted, because a plain fetch() with no timeout can hang
// forever with nothing on screen to show for it, and nothing ever recovers.
//
// AuthGate does its own bounded session check after mounting (fetchSession,
// which now has a hard timeout and self-heals the package id -- see
// lib/api.ts), so nothing here depends on bootstrapConfig succeeding, or even
// finishing. It still runs, purely as a best-effort head start for the id used
// while nobody is signed in yet.
bootstrapConfig();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <AuthGate>
        <Root />
      </AuthGate>
    </ErrorBoundary>
  </StrictMode>,
);
