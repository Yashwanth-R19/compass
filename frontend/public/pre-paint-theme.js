// Pre-paint theme application (UI rebuild session 1, Part D) -- runs before
// any stylesheet, so the correct theme is on <html> before the first paint,
// avoiding a light-to-dark flash. Dark is the app's UNCONDITIONAL default:
// this reads localStorage['compass-theme'] and applies "light" ONLY when
// that value is exactly "light" -- there is no prefers-color-scheme
// fallback here, matching src/theme/ThemeProvider.tsx's readInitialTheme()
// exactly. If you change one, change the other -- they must agree exactly.
//
// A SEPARATE, same-origin file rather than an inline <script> in
// index.html (which is where this lived through UI rebuild sessions 1-3) --
// moved here in session 4, Part H, after this session's own production CSP
// verification found the inline version was silently blocked by
// frontend/vercel.json's `script-src 'self'` (no 'unsafe-inline', no
// nonce, no hash -- inline scripts have no exemption under that policy).
// An external same-origin script needs no CSP change at all, and avoids
// the alternative fix (a `sha256-...` hash entry in vercel.json) going
// silently stale the next time anyone edits this file's content without
// also updating that hash.
(function () {
  try {
    var stored = window.localStorage.getItem("compass-theme");
    document.documentElement.setAttribute("data-theme", stored === "light" ? "light" : "dark");
  } catch {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
