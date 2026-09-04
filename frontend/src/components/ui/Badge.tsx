import type { ReactNode } from "react";

type Tone = "neutral" | "accent" | "high" | "med" | "low";

// `high`/`med`/`low` map onto danger/warning/success -- a filled chip
// (soft tint + solid text), the SAME pattern as `lib/format.ts::
// SEVERITY_CLASSES`, which this mirrors exactly. SeverityChip and Badge's
// severity tones are the same visual language, not two implementations of
// it.
const OUTLINE_TONE: Record<"neutral" | "accent", string> = {
  neutral: "border border-border text-text-muted",
  accent: "border border-accent text-accent",
};
const FILL_TONE: Record<"high" | "med" | "low", string> = {
  high: "bg-danger-bg text-danger",
  med: "bg-warning-bg text-warning",
  low: "bg-success-bg text-success",
};

/** A small static label. `neutral`/`accent` are a hairline-bordered
 * outline, no fill; `high`/`med`/`low` (severity) are a solid fill --
 * see `FILL_TONE`'s own comment for why the two tones can't share one
 * visual treatment. This is the generic primitive; SeverityChip/
 * SubsystemBadge/ContributorChip are all specific USES of this shape with
 * their own semantics layered on top, not separate visual languages. */
export function Badge({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  const toneClass =
    tone === "high" || tone === "med" || tone === "low" ? FILL_TONE[tone] : OUTLINE_TONE[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-xs px-1.5 py-0.5 text-xs font-medium ${toneClass} ${className}`}
    >
      {children}
    </span>
  );
}
