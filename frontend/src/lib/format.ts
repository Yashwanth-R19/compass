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

/** A filled chip per severity -- a soft self-tinted background plus solid
 * text in the same hue, the SAME pattern every other status colour in this
 * app already uses (Alert's `border-danger text-danger`, Badge's
 * `bg-danger-bg`, ...) rather than a solid fill from the heat ramp with a
 * hand-picked ink colour: a `*-bg` tint is by construction close to
 * `--color-bg-elevated`, so the solid-hue text on top of it clears
 * contrast the same way it already does as plain foreground text
 * elsewhere in the app, with no per-palette contrast re-engineering
 * needed. `high`/`med`/`low` map onto danger/warning/success -- three
 * distinct hues, never a bare red/green pair. Always paired with
 * SEVERITY_LABEL's text, never colour alone (WCAG 1.4.1). */
export const SEVERITY_CLASSES: Record<Severity, string> = {
  high: "bg-danger-bg text-danger",
  med: "bg-warning-bg text-warning",
  low: "bg-success-bg text-success",
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
