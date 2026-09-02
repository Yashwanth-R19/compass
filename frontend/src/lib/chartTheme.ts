/**
 * The single source of colour/typography for every renderer that draws
 * outside the DOM's own CSS cascade: recharts (SVG, but styled via JS
 * props, not className), react-force-graph-2d (a `<canvas>`), d3-hierarchy
 * treemaps (plain fill colours computed in JS), and three.js (session 09's
 * 3D city -- Known Hazards #4/#5, CLAUDE.md). None of these read CSS custom
 * properties on their own, so this module reads them ONCE, via
 * `getComputedStyle(document.documentElement)`, and hands back plain hex
 * strings every one of those four renderers can consume directly.
 *
 * RULE, stated once here rather than at each call site: colour encodes
 * DATA -- severity, risk, confidence, recency, subsystem identity, compare
 * direction -- and nothing else. Chrome (axis lines, grid lines, tooltip
 * background/surface, legend text) is always drawn from the neutral
 * ink/border tokens, never from a data hue. If you are about to reach for a
 * bright
 * colour to make a chart "pop" and it isn't one of the palettes below,
 * that's chartjunk -- don't.
 *
 * Every constant here has a fallback baked in (`readVar`'s second
 * argument), so this module also works correctly in Vitest's jsdom
 * environment, which never loads styles/tokens.css -- `getComputedStyle`
 * there returns an empty string for every custom property, and the
 * fallback (the SAME light-mode value declared in tokens.css, kept in sync
 * by hand) is what tests actually exercise. Read once at module load, not
 * re-read on a theme change mid-session (Known Hazard, CLAUDE.md Part C) --
 * a page that must react to the OS theme changing while open would need a
 * `matchMedia` listener, which nothing in this codebase needs today.
 */

function readVar(name: string, fallback: string): string {
  if (typeof document === "undefined" || typeof getComputedStyle !== "function") {
    return fallback;
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function toHexByte(v: number): string {
  return Math.round(Math.max(0, Math.min(255, v)))
    .toString(16)
    .padStart(2, "0");
}

/** Linear RGB interpolation between two `#rrggbb` colours, clamped to
 * [0, 1]. Pure and deterministic -- the same (colourA, colourB, t) always
 * produces the same result, in any renderer. */
export function lerpColor(colorA: string, colorB: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(colorA);
  const [br, bg, bb] = hexToRgb(colorB);
  const clamped = Math.max(0, Math.min(1, t));
  return `#${toHexByte(ar + (br - ar) * clamped)}${toHexByte(ag + (bg - ag) * clamped)}${toHexByte(ab + (bb - ab) * clamped)}`;
}

/** Interpolates across an ordered list of stops (a multi-point sequential
 * scale, e.g. the 5-stop risk "heat" ramp) rather than just two endpoints --
 * a richer gradient than a 2-point lerp while staying just as deterministic
 * and just as pure. `t` outside [0, 1] clamps to the nearest end stop. */
export function lerpScale(stops: readonly string[], t: number): string {
  if (stops.length === 0) return "#000000";
  if (stops.length === 1) return stops[0];
  const clamped = Math.max(0, Math.min(1, t));
  const span = (stops.length - 1) * clamped;
  const i = Math.min(stops.length - 2, Math.floor(span));
  return lerpColor(stops[i], stops[i + 1], span - i);
}

// ---- Subsystem categorical palette --------------------------------------
// Fallbacks mirror styles/tokens.css's :root block exactly -- keep the two
// in sync by hand if the palette is ever revisited (session 09 Part A /
// session 15 Part A).
const SUBSYSTEM_FALLBACKS = [
  "#0072b2",
  "#e69f00",
  "#009e73",
  "#cc79a7",
  "#56b4e9",
  "#d55e00",
  "#f0c808",
  "#7b3294",
  "#994f00",
  "#117733",
  "#7216f3",
  "#4d4d4d",
] as const;

export const SUBSYSTEM_PALETTE: readonly string[] = SUBSYSTEM_FALLBACKS.map((fallback, i) =>
  readVar(`--subsystem-${i + 1}`, fallback),
);

export const UNASSIGNED_COLOR: string = readVar("--subsystem-unassigned", "#948d7c");

// ---- Sequential risk scale ("heat": straw -> deep red) -------------------
export const RISK_SCALE: readonly string[] = [
  readVar("--cp-risk-0", "#f4e6bf"),
  readVar("--cp-risk-1", "#e8b366"),
  readVar("--cp-risk-2", "#d97b3f"),
  readVar("--cp-risk-3", "#b6432c"),
  readVar("--cp-risk-4", "#7f1d1d"),
];
export const RISK_LOW = RISK_SCALE[0];
export const RISK_HIGH = RISK_SCALE[RISK_SCALE.length - 1];

// ---- Recency (fresh -> stale) --------------------------------------------
export const RECENCY_FRESH: string = readVar("--cp-recency-fresh", "#0e7490");
export const RECENCY_STALE: string = UNASSIGNED_COLOR;

// ---- Diverging (session 13 compare: improved / worsened / neutral) -------
export const DIVERGING_IMPROVE: string = readVar("--cp-diverging-improve", "#1d6fa5");
export const DIVERGING_WORSEN: string = readVar("--cp-diverging-worsen", "#b6432c");
export const DIVERGING_NEUTRAL: string = readVar("--cp-diverging-neutral", "#8d8571");

// ---- Severity / confidence -------------------------------------------
export const SEVERITY_COLOR = {
  high: readVar("--cp-sev-high", "#b91c1c"),
  med: readVar("--cp-sev-med", "#b45309"),
  low: readVar("--cp-sev-low", "#57534e"),
};

export const CONFIDENCE_COLOR = {
  low: readVar("--cp-conf-low", "#b45309"),
  medium: readVar("--cp-conf-medium", "#5f594a"),
  high: readVar("--cp-conf-high", "#15803d"),
};

// ---- Chrome (never data -- axis/grid/tooltip/legend) ---------------------
export const CHROME = {
  bg: readVar("--cp-bg", "#f2f0eb"),
  surface: readVar("--cp-surface", "#ffffff"),
  border: readVar("--cp-border", "#dedad0"),
  ink: readVar("--cp-ink", "#17150f"),
  inkMuted: readVar("--cp-ink-muted", "#5f594a"),
  inkFaint: readVar("--cp-ink-faint", "#726c5c"),
  signal: readVar("--cp-signal", "#0f6f75"),
  fontMono:
    '"Berkeley Mono","JetBrains Mono",ui-monospace,"SFMono-Regular","Cascadia Code","Roboto Mono",Menlo,Consolas,monospace',
};

/** Shared recharts prop bundles -- every chart in the app should spread
 * these onto its `CartesianGrid`/axis/`Tooltip` rather than hand-picking
 * stroke/fill colours per chart, which is how the old codebase ended up
 * with each page's charts looking subtly different. */
export const rechartsTheme = {
  grid: { stroke: CHROME.border, strokeDasharray: "2 2" },
  axis: {
    stroke: CHROME.border,
    tick: { fill: CHROME.inkFaint, fontSize: 11, fontFamily: CHROME.fontMono },
  },
  tooltip: {
    contentStyle: {
      background: CHROME.surface,
      border: `1px solid ${CHROME.border}`,
      borderRadius: 0,
      color: CHROME.ink,
      fontSize: 12,
      fontFamily: CHROME.fontMono,
      boxShadow: "none",
    },
    labelStyle: { color: CHROME.inkMuted },
    itemStyle: { color: CHROME.ink },
    cursor: { fill: CHROME.border, opacity: 0.4 },
  },
  legend: { fontSize: 11, color: CHROME.inkMuted, fontFamily: CHROME.fontMono },
} as const;

/** Score/value in [0, 1] -> a colour on the risk heat scale. */
export function riskScaleColor(t: number): string {
  return lerpScale(RISK_SCALE, t);
}
