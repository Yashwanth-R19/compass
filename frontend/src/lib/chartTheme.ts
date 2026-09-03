/**
 * The single source of colour/typography for every renderer that draws
 * outside the DOM's own CSS cascade: recharts (SVG, but styled via JS
 * props, not className), react-force-graph-2d (a `<canvas>`), d3-hierarchy
 * treemaps (plain fill colours computed in JS), and three.js (the 3D
 * city). None of these read CSS custom properties on their own, so this
 * module reads them ONCE, via `getComputedStyle(document.documentElement)`,
 * and hands back plain hex strings every one of those four renderers can
 * consume directly.
 *
 * RULE, stated once here rather than at each call site: colour encodes
 * DATA -- severity, risk, confidence, recency, subsystem identity, compare
 * direction -- and nothing else. Chrome (axis lines, grid lines, tooltip
 * background/surface, legend text) is always drawn from the neutral
 * text/border tokens, never from a data hue. If you are about to reach for
 * a bright colour to make a chart "pop" and it isn't one of the palettes
 * below, that's chartjunk -- don't.
 *
 * Every constant here has a fallback baked in (`readVar`'s second
 * argument), so this module also works correctly in Vitest's jsdom
 * environment, which never loads styles/tokens.css -- `getComputedStyle`
 * there returns an empty string for every custom property, and the
 * fallback (the SAME dark-mode value declared in tokens.css, kept in sync
 * by hand -- dark is this app's default scheme) is what tests actually
 * exercise. Read once at module load, not re-read on a theme change
 * mid-session -- a page that must react to the theme toggle while open
 * would need a MutationObserver on `data-theme`, which nothing in this
 * codebase needs today.
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
 * scale, e.g. the 6-stop heat ramp) rather than just two endpoints -- a
 * richer gradient than a 2-point lerp while staying just as deterministic
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
// in sync by hand if the palette is ever revisited.
const SUBSYSTEM_FALLBACKS = [
  "#5fb99a",
  "#bfb740",
  "#913030",
  "#425f80",
  "#9cc379",
  "#a87438",
  "#7291ac",
  "#c75766",
  "#578bc7",
  "#80424e",
  "#c2cf6e",
  "#a1935e",
] as const;

export const SUBSYSTEM_PALETTE: readonly string[] = SUBSYSTEM_FALLBACKS.map((fallback, i) =>
  readVar(`--subsystem-${i + 1}`, fallback),
);

export const UNASSIGNED_COLOR: string = readVar("--subsystem-unassigned", "#7e8496");

// ---- Sequential heat ramp (severity/risk: neutral -> deep, section 3.1) --
// Six stops -- dark-mode (this app's default) fallbacks, matching
// tokens.css's base :root block.
export const RISK_SCALE: readonly string[] = [
  readVar("--scale-0", "#8a8f80"),
  readVar("--scale-1", "#c9be8a"),
  readVar("--scale-2", "#d3a04a"),
  readVar("--scale-3", "#c97b4a"),
  readVar("--scale-4", "#b85c4e"),
  readVar("--scale-5", "#9e4038"),
];
export const RISK_LOW = RISK_SCALE[0];
export const RISK_HIGH = RISK_SCALE[RISK_SCALE.length - 1];

// ---- Recency (fresh -> stale) --------------------------------------------
export const RECENCY_FRESH: string = readVar("--cp-accent", "#5fb99a");
export const RECENCY_STALE: string = UNASSIGNED_COLOR;

// ---- Diverging (compare: improved / worsened / neutral) ------------------
export const DIVERGING_IMPROVE: string = readVar("--cp-accent", "#5fb99a");
export const DIVERGING_WORSEN: string = readVar("--scale-3", "#c97b4a");
export const DIVERGING_NEUTRAL: string = readVar("--cp-text-muted", "#8a8f80");

// ---- Severity / confidence -------------------------------------------
// Severity reads only from the heat ramp (section 3.1: "nowhere else").
export const SEVERITY_COLOR = {
  high: RISK_SCALE[5],
  med: RISK_SCALE[3],
  low: RISK_SCALE[1],
};

// Confidence is a stepped bar glyph (never a colour scale of its own,
// section 3.1) -- kept here only because a couple of chart contexts (e.g.
// a scatter plot's point colour) need a plain colour per tier rather than
// the bar glyph itself. Fixed per-position tones, same as
// components/ConfidenceMeter.tsx: muted / text / accent for low / medium /
// high, never a hue implying "bad".
export const CONFIDENCE_COLOR = {
  low: readVar("--cp-text-muted", "#8a8f80"),
  medium: readVar("--cp-text", "#c2c6b9"),
  high: readVar("--cp-accent", "#5fb99a"),
};

// ---- Chrome (never data -- axis/grid/tooltip/legend) ---------------------
export const CHROME = {
  bg: readVar("--cp-bg", "#0b0c0a"),
  surface: readVar("--cp-bg-elevated", "#131512"),
  border: readVar("--cp-border", "#242821"),
  ink: readVar("--cp-text", "#c2c6b9"),
  inkMuted: readVar("--cp-text-muted", "#8a8f80"),
  inkFaint: readVar("--cp-text-muted", "#8a8f80"),
  signal: readVar("--cp-accent", "#5fb99a"),
  fontMono:
    '"JetBrains Mono Variable","JetBrains Mono",ui-monospace,"SFMono-Regular","Cascadia Code","Roboto Mono",Menlo,Consolas,monospace',
};

/** Shared recharts prop bundles -- every chart in the app should spread
 * these onto its `CartesianGrid`/axis/`Tooltip` rather than hand-picking
 * stroke/fill colours per chart. */
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
      borderRadius: 5,
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

/** Score/value in [0, 1] -> a colour on the heat ramp. */
export function riskScaleColor(t: number): string {
  return lerpScale(RISK_SCALE, t);
}
