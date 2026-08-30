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

// Inter, for the exploratory Linear/Stripe-style comparison UI only (#linear route).
// The shipped despatch register never uses it.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";

import Root from "./Root.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
