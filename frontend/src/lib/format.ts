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

/** One hairline-bordered chip per severity, no fill -- consistent with
 * every other status chip in the app (Badge's `tone` variants share this
 * same shape). Always paired with SEVERITY_LABEL's text, never colour
 * alone (WCAG 1.4.1). */
export const SEVERITY_CLASSES: Record<Severity, string> = {
  high: "border-sev-high text-sev-high",
  med: "border-sev-med text-sev-med",
  low: "border-sev-low text-sev-low",
};

export function confidenceLabel(confidence: number): "low" | "medium" | "high" {
  if (confidence < 0.4) return "low";
  if (confidence < 0.75) return "medium";
  return "high";
}

export function healthColor(score: number): { text: string; ring: string; bar: string } {
  if (score >= 75) {
    return { text: "text-conf-high", ring: "stroke-conf-high", bar: "bg-conf-high" };
  }
  if (score >= 50) {
    return { text: "text-conf-low", ring: "stroke-conf-low", bar: "bg-conf-low" };
  }
  return { text: "text-sev-high", ring: "stroke-sev-high", bar: "bg-sev-high" };
}

export function fileName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] ?? path;
}
