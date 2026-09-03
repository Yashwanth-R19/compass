import { Gauge, Info, Scale } from "lucide-react";

export type HonestyNoteVariant = "scope-limitation" | "confidence-caveat" | "calibration";

const ICON = {
  "scope-limitation": Info,
  "confidence-caveat": Gauge,
  calibration: Scale,
} as const;

/**
 * The one component for every statement in the explainability doctrine's
 * honesty registry (plan/UI_REBUILD_SESSIONS.md section 5.3) — Compass's
 * refusal to claim more than it measured, made a VISIBLE statement rather
 * than a buried footnote. Three variants: `scope-limitation` (what was not
 * measured — e.g. the evolution timeline's "this is churn-ranked, not risk
 * over time"), `confidence-caveat` (how sure Compass is about a specific
 * number — e.g. "this repository had too few commits for the normal
 * coupling floor"), and `calibration` (whether a score is heuristic or
 * corpus-calibrated).
 *
 * Renders inline in the normal document flow — never behind a toggle,
 * never below the fold, never as a dismissible tooltip. `text` is a prop,
 * not a lookup, specifically so a caller can pass either a fixed string
 * from `content/explainability.ts`'s `HONESTY` registry OR — whenever the
 * backend already returns the exact sentence (`TimelineResponse.not_covered`,
 * `TestGapsResponse.limitation`, `GlossaryResponse.limitation`,
 * `unreferenced_files_caveat`, `secrets_caveat`, `pooled_distribution_label`,
 * `corpus_note`, the truck-factor `interpretation`) — that API string
 * verbatim, never a local paraphrase that could drift out of sync with it.
 *
 * Visually quiet (a hairline left border, muted body text) by design — an
 * honesty note is not an error or a warning, it's context. It must never be
 * styled to look alarming, which would train a reader to skip past it.
 */
export function HonestyNote({
  variant,
  text,
  className = "",
}: {
  variant: HonestyNoteVariant;
  text: string;
  className?: string;
}) {
  const Icon = ICON[variant];
  return (
    <p
      className={`flex items-start gap-2 border-l-2 border-border-strong py-1.5 pl-3 text-xs leading-relaxed text-text-muted ${className}`}
    >
      <Icon size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{text}</span>
    </p>
  );
}
