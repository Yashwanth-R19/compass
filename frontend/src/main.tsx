import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-hosted variable fonts (Part A/D) -- no runtime Google Fonts request.
// Newsreader's italic axis is imported too (used for pull-quote-style
// emphasis in prose, section 3.2).
import "@fontsource-variable/newsreader";
import "@fontsource-variable/newsreader/wght-italic.css";
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
