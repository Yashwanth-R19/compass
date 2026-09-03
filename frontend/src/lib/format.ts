import type { Severity } from "../api/types";

export function shortSha(sha: string | null | undefined): string {
  if (!sha) return "—";
  return sha.slice(0, 7);
}

export function formatPercent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatScore(value: number, digits = 2): string {
  return value.toFixed(digits);
}

export const SEVERITY_ORDER: Record<Severity, number> = { high: 2, med: 1, low: 0 };

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High",
  med: "Medium",
  low: "Low",
};

/** A FILLED chip per severity (background = the heat-ramp stop itself),
 * reading only from the six-stop heat ramp (design tokens section 3.1:
 * "severity maps onto that ramp and nowhere else") -- high = scale-5,
 * med = scale-3, low = scale-1. Always paired with SEVERITY_LABEL's text,
 * never colour alone (WCAG 1.4.1).
 *
 * NOT a hairline-bordered outline (unlike Badge's other tones) --
 * measured this session: scale-5 (dark scheme) is only 2.84:1 against
 * --color-bg-elevated as text/border, below even the 3:1 non-text bar,
 * and scale-1 (light scheme) is 3.37:1, short of the 4.5:1 body-text bar.
 * A solid fill with a per-tier FIXED ink colour (chosen specifically per
 * severity level -- see tokens.css's own comment on
 * --color-scale-ink-dark/-light for why a single generic choice doesn't
 * work) is what actually clears contrast at every tier, in both schemes,
 * with real margin. `med` is the one tier that needs a scheme-conditional
 * ink (dark ink in dark scheme, light ink in light scheme) -- `dark:`
 * here correctly tracks the app's own manual theme toggle
 * (index.css's `@custom-variant dark`), not the OS setting. */
export const SEVERITY_CLASSES: Record<Severity, string> = {
  high: "bg-scale-5 text-scale-ink-light",
  med: "bg-scale-3 text-scale-ink-light dark:text-scale-ink-dark",
  low: "bg-scale-1 text-scale-ink-dark",
};

export function confidenceLabel(confidence: number): "low" | "medium" | "high" {
  if (confidence < 0.4) return "low";
  if (confidence < 0.75) return "medium";
  return "high";
}

/** General-purpose good/medium/bad status tone -- deliberately the three
 * named status tones (success/warning/danger), never the heat ramp, which
 * is reserved for severity specifically (section 3.1). */
export function healthColor(score: number): { text: string; ring: string; bar: string } {
  if (score >= 75) {
    return { text: "text-success", ring: "stroke-success", bar: "bg-success" };
  }
  if (score >= 50) {
    return { text: "text-warning", ring: "stroke-warning", bar: "bg-warning" };
  }
  return { text: "text-danger", ring: "stroke-danger", bar: "bg-danger" };
}

export function fileName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] ?? path;
}
