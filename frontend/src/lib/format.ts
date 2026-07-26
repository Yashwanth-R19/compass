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

export const SEVERITY_CLASSES: Record<Severity, string> = {
  high: "bg-red-100 text-red-700 ring-red-600/20 dark:bg-red-500/10 dark:text-red-400 dark:ring-red-500/30",
  med: "bg-amber-100 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-500/30",
  low: "bg-slate-100 text-slate-600 ring-slate-500/20 dark:bg-slate-500/10 dark:text-slate-400 dark:ring-slate-500/30",
};

export function confidenceLabel(confidence: number): "low" | "medium" | "high" {
  if (confidence < 0.4) return "low";
  if (confidence < 0.75) return "medium";
  return "high";
}

export function healthColor(score: number): { text: string; ring: string; bar: string } {
  if (score >= 75) {
    return {
      text: "text-emerald-600 dark:text-emerald-400",
      ring: "stroke-emerald-500",
      bar: "bg-emerald-500",
    };
  }
  if (score >= 50) {
    return {
      text: "text-amber-600 dark:text-amber-400",
      ring: "stroke-amber-500",
      bar: "bg-amber-500",
    };
  }
  return { text: "text-red-600 dark:text-red-400", ring: "stroke-red-500", bar: "bg-red-500" };
}

export function fileName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] ?? path;
}
