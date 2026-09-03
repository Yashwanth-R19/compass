import { confidenceLabel, formatPercent } from "../lib/format";

const TIER_SEGMENTS: Record<"low" | "medium" | "high", number> = { low: 1, medium: 2, high: 3 };

/** Section 3.1: "Confidence is never encoded by hue and never by opacity.
 * It is a stepped three-bar glyph: filled bars use --color-text-muted (1),
 * --color-text (2), --color-accent (3); unfilled bars use
 * --color-border-strong." Each bar's colour is therefore fixed to ITS OWN
 * position, not the overall tier -- a low-confidence value shows exactly
 * one filled (muted-grey) bar and two unfilled ones, never a "low = amber"
 * hue the way severity/health do. */
const BAR_COLOR = ["bg-text-muted", "bg-text", "bg-accent"];

/** How sure Compass is, rendered as a SEPARATE visual dimension from a
 * risk/finding score -- never opacity, never a fade (a faded row would
 * read as "less risky", which is the wrong message; the file is exactly as
 * risky, just less certain -- master-context.md sec 8.1: risk_confidence
 * is independent of risk_score and must be shown as such). A stepped
 * "signal bars" glyph (1-3 bars of increasing height) plus the
 * percentage, completely different in shape from the flat width-fill bar
 * risk_score renders with elsewhere, so the two can never be mistaken for
 * variants of the same meter. */
export function ConfidenceMeter({
  confidence,
  size = "md",
  className = "",
}: {
  confidence: number;
  size?: "sm" | "md";
  className?: string;
}) {
  const tier = confidenceLabel(confidence);
  const filled = TIER_SEGMENTS[tier];
  const barWidth = size === "sm" ? "w-1" : "w-1.5";
  const heights = size === "sm" ? [4, 6, 8] : [6, 9, 12];

  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      title={`Confidence: how much history backs this — ${formatPercent(confidence)} (${tier})`}
    >
      <span className="flex items-end gap-0.5" aria-hidden="true">
        {heights.map((h, i) => (
          <span
            key={i}
            className={`${barWidth} rounded-[1px] ${i < filled ? BAR_COLOR[i] : "bg-border-strong"}`}
            style={{ height: h }}
          />
        ))}
      </span>
      <span
        className={`tabular-nums ${size === "sm" ? "text-xs" : "text-sm"} ${
          tier === "low" ? "font-medium text-text" : "text-text-muted"
        }`}
      >
        {formatPercent(confidence)} confidence{tier === "low" ? " (low)" : ""}
      </span>
    </span>
  );
}
