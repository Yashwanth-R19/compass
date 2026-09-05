import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-hosted fonts -- no runtime Google Fonts request. Fraunces (display
// serif -- wordmark, hero, section headings, evidence blockquotes) replaces
// Cormorant Garamond (user-requested restyling pass, no longer following
// the Aporia port verbatim): a "wonky", optical-size-aware editorial serif
// with real personality at large display sizes, still calm and legible as
// a heading face at UI scale. The variable file covers its full weight
// range in one request; its italic axis is used the same way Cormorant's
// was, for pull-quote-style emphasis in prose.
import "@fontsource-variable/fraunces";
import "@fontsource-variable/fraunces/standard-italic.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";
import { ThemeProvider } from "./theme/ThemeProvider";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
);
