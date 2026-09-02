import { confidenceLabel, formatPercent } from "../lib/format";

const TIER_SEGMENTS: Record<"low" | "medium" | "high", number> = { low: 1, medium: 2, high: 3 };

const TIER_COLOR: Record<"low" | "medium" | "high", string> = {
  low: "bg-conf-low",
  medium: "bg-conf-medium",
  high: "bg-conf-high",
};

/** How sure Compass is, rendered as a SEPARATE visual dimension from a
 * risk/finding score -- never opacity, never a fade (Known Hazard #3: a
 * faded row reads as "less risky", which is the wrong message; the file is
 * exactly as risky, just less certain). A stepped "signal bars" glyph (1-3
 * bars of increasing height) plus the percentage and, when low, an explicit
 * amber-family label -- a completely different shape from the flat
 * width-fill bar `risk_score` renders with elsewhere, so the two can never
 * be mistaken for variants of the same meter. `master-context.md` sec 8.1 /
 * RULES.md sec 3: risk_confidence is independent of risk_score and must be
 * shown as such. */
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
            className={`${barWidth} ${i < filled ? TIER_COLOR[tier] : "bg-surface-inset"}`}
            style={{ height: h }}
          />
        ))}
      </span>
      <span
        className={`tabular-nums ${size === "sm" ? "text-xs" : "text-sm"} ${
          tier === "low" ? "font-medium text-conf-low" : "text-ink-muted"
        }`}
      >
        {formatPercent(confidence)} confidence{tier === "low" ? " (low)" : ""}
      </span>
    </span>
  );
}
