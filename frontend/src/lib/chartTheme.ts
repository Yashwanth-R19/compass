/**
 * The single source of colour/typography for every renderer that draws
 * outside the DOM's own CSS cascade -- recharts (SVG, but styled via JS
 * props, not className). None of these read CSS custom properties on
 * their own, so this module reads them ONCE, via
 * `getComputedStyle(document.documentElement)`, and hands back plain hex
 * strings recharts can consume directly.
 *
 * RULE, stated once here rather than at each call site: colour encodes
 * DATA -- severity, risk, confidence, recency, subsystem identity, compare
 * direction -- and nothing else. Chrome (axis lines, grid lines, tooltip
 * background/surface, legend text) is always drawn from the neutral
 * text/border tokens, never from a data hue.
 *
 * Every constant here has a fallback baked in (`readVar`'s second
 * argument), so this module also works correctly in Vitest's jsdom
 * environment, which never loads styles/tokens.css -- `getComputedStyle`
 * there returns an empty string for every custom property, and the
 * fallback (the SAME dark-mode value declared in tokens.css, kept in sync
 * by hand -- dark is this app's default scheme) is what tests actually
 * exercise. Read once at module load, not re-read on a theme change
 * mid-session.
 */
import { CATEGORICAL_PALETTE, colorForKey } from "./palette";

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
 * scale, e.g. the 6-stop heat ramp) rather than just two endpoints. `t`
 * outside [0, 1] clamps to the nearest end stop. */
export function lerpScale(stops: readonly string[], t: number): string {
  if (stops.length === 0) return "#000000";
  if (stops.length === 1) return stops[0];
  const clamped = Math.max(0, Math.min(1, t));
  const span = (stops.length - 1) * clamped;
  const i = Math.min(stops.length - 2, Math.floor(span));
  return lerpColor(stops[i], stops[i + 1], span - i);
}

// ---- Categorical palette (subsystems, contributors, languages, ...) -----
// The single source of truth is lib/palette.ts (rebuild spec section 5.4);
// re-exported under its pre-existing name so every already-written chart
// call site keeps working unchanged.
export const SUBSYSTEM_PALETTE: readonly string[] = CATEGORICAL_PALETTE;
export const UNASSIGNED_COLOR: string = colorForKey(null);

// ---- Sequential heat ramp (severity/risk: neutral -> deep, tokens.css) --
// Six stops -- dark-mode (this app's default) fallbacks, matching
// tokens.css's base :root block.
export const RISK_SCALE: readonly string[] = [
  readVar("--scale-0", "#7e848f"),
  readVar("--scale-1", "#7b9d73"),
  readVar("--scale-2", "#a89359"),
  readVar("--scale-3", "#cf8b43"),
  readVar("--scale-4", "#d48b6e"),
  readVar("--scale-5", "#d98a98"),
];
export const RISK_LOW = RISK_SCALE[0];
export const RISK_HIGH = RISK_SCALE[RISK_SCALE.length - 1];

// ---- Recency (fresh -> stale) --------------------------------------------
export const RECENCY_FRESH: string = readVar("--cp-accent", "#d6ac4d");
export const RECENCY_STALE: string = UNASSIGNED_COLOR;

// ---- Diverging (compare: improved / worsened / neutral) ------------------
export const DIVERGING_IMPROVE: string = readVar("--cp-accent", "#d6ac4d");
export const DIVERGING_WORSEN: string = readVar("--cp-danger", "#d98a98");
export const DIVERGING_NEUTRAL: string = readVar("--cp-text-muted", "#7e848f");

// ---- Severity / confidence -------------------------------------------
// Severity reads from the three named status tones (danger/warning/
// success) -- lib/format.ts::SEVERITY_CLASSES' own docstring explains why
// this moved off the heat ramp's raw fill values (a text-legibility
// concern the heat ramp's own graduated stops don't need to solve).
export const SEVERITY_COLOR = {
  high: readVar("--cp-danger", "#d98a98"),
  med: readVar("--cp-warning", "#cf8b43"),
  low: readVar("--cp-success", "#5fa383"),
};

// Confidence is a stepped bar glyph (never a colour scale of its own) --
// kept here only because a couple of chart contexts (e.g. a scatter plot's
// point colour) need a plain colour per tier rather than the bar glyph
// itself. Fixed per-position tones, same as components/ConfidenceMeter.tsx:
// muted / text / accent for low / medium / high, never a hue implying "bad".
export const CONFIDENCE_COLOR = {
  low: readVar("--cp-text-muted", "#7e848f"),
  medium: readVar("--cp-text", "#c3c7ce"),
  high: readVar("--cp-accent", "#d6ac4d"),
};

// ---- Chrome (never data -- axis/grid/tooltip/legend) ---------------------
export const CHROME = {
  bg: readVar("--cp-bg", "#0a0b0d"),
  surface: readVar("--cp-bg-elevated", "#121418"),
  border: readVar("--cp-border", "#23262d"),
  ink: readVar("--cp-text", "#c3c7ce"),
  inkMuted: readVar("--cp-text-muted", "#7e848f"),
  inkFaint: readVar("--cp-text-muted", "#7e848f"),
  signal: readVar("--cp-accent", "#d6ac4d"),
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
      borderRadius: 6,
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
