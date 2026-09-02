import type { ReactNode } from "react";

type Tone = "neutral" | "signal" | "high" | "med" | "low";

const TONE: Record<Tone, string> = {
  neutral: "border-border text-ink-muted",
  signal: "border-signal text-signal",
  high: "border-sev-high text-sev-high",
  med: "border-sev-med text-sev-med",
  low: "border-sev-low text-sev-low",
};

/** A small static label -- one hairline border, no fill, no pill shape
 * (Part A: sharp corners). This is the generic primitive; SeverityChip,
 * SubsystemBadge, and ContributorChip are all specific *uses* of this
 * shape with their own semantics layered on top, not separate visual
 * languages. */
export function Badge({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 border px-1.5 py-0.5 text-xs font-medium ${TONE[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
