import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-hosted fonts -- no runtime Google Fonts request. Cormorant Garamond
// (display serif -- wordmark, hero, section headings, evidence
// blockquotes) replaces the outgoing Newsreader (rebuild spec section 5.4);
// its italic weights are used for pull-quote-style emphasis in prose.
import "@fontsource/cormorant-garamond/400.css";
import "@fontsource/cormorant-garamond/400-italic.css";
import "@fontsource/cormorant-garamond/500.css";
import "@fontsource/cormorant-garamond/600.css";
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
