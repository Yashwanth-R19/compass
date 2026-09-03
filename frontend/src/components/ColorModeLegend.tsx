import { colorForSubsystem, UNASSIGNED_COLOR } from "../lib/subsystemColors";
import { RECENCY_FRESH, RISK_HIGH, RISK_LOW } from "../lib/chartTheme";

export type ColorLegendMode = "subsystem" | "risk" | "owner" | "recency";

/**
 * The shared colour-mode legend for the codebase map's subsystem graph and
 * its directory-treemap view -- both use the identical four colour modes
 * (subsystem/risk/owner/recency), and "every colour mode states what it
 * encodes" (UI rebuild session 3, Part B) applies to both. Mirrors the
 * shape of `CodeCity.tsx`'s own local `Legend`/`GradientLegend`/`Swatch`
 * trio (kept local there since the city has a fifth mode, "test vs
 * source", and a height dimension neither of these two views has) rather
 * than forcing one over-generalised component across all three renderers.
 */
export function ColorModeLegend({
  mode,
  subsystemLabels,
}: {
  mode: ColorLegendMode;
  /** Only meaningful for "subsystem" mode -- the labels actually present in
   * the current view, so the legend never lists a subsystem that isn't
   * shown. */
  subsystemLabels?: string[];
}) {
  if (mode === "subsystem") {
    return (
      <div className="flex flex-wrap items-center gap-2">
        {(subsystemLabels ?? []).map((label) => (
          <span
            key={label}
            className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-[11px] text-text-muted"
          >
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: colorForSubsystem(label) }}
            />
            {label}
          </span>
        ))}
      </div>
    );
  }

  if (mode === "risk") {
    return (
      <GradientSwatch lowLabel="Low risk" highLabel="High risk" low={RISK_LOW} high={RISK_HIGH} />
    );
  }

  if (mode === "recency") {
    return (
      <GradientSwatch
        lowLabel="Stale"
        highLabel="Recently changed"
        low={UNASSIGNED_COLOR}
        high={RECENCY_FRESH}
      />
    );
  }

  return (
    <p className="text-[11px] text-text-muted">
      Colour = principal author. Each distinct colour is one contributor; hover or select a file to
      see who.
    </p>
  );
}

function GradientSwatch({
  lowLabel,
  highLabel,
  low,
  high,
}: {
  lowLabel: string;
  highLabel: string;
  low: string;
  high: string;
}) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-text-muted">
      <span>{lowLabel}</span>
      <span
        className="h-2.5 w-24 rounded-full"
        style={{ background: `linear-gradient(to right, ${low}, ${high})` }}
      />
      <span>{highLabel}</span>
    </div>
  );
}
