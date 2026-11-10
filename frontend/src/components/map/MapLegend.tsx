import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { MAP_COPY } from "../../content/map";
import { TOOLTIPS } from "../../content/explainability";
import { activityColor, type ActivityBucket } from "../../lib/diagram/activity";
import { InfoTooltip } from "../ui/InfoTooltip";

function Swatch({ stroke, dashed, arrow }: { stroke: string; dashed?: boolean; arrow?: boolean }) {
  return (
    <svg width="28" height="10" aria-hidden="true" className="shrink-0">
      <line
        x1="1"
        y1="5"
        x2={arrow ? 21 : 27}
        y2="5"
        stroke={stroke}
        strokeWidth="2"
        strokeDasharray={dashed ? "4 3" : undefined}
      />
      {arrow ? <path d="M20,1 L27,5 L20,9 z" fill={stroke} /> : null}
    </svg>
  );
}

/** Collapsible key in the canvas corner; excluded from image exports. */
export function MapLegend({ activityOn }: { activityOn: boolean }) {
  const [open, setOpen] = useState(
    () => typeof window === "undefined" || window.matchMedia("(min-width: 1280px)").matches,
  );
  const Icon = open ? ChevronDown : ChevronRight;
  const ramp: ActivityBucket[] = [0, 1, 2, 3, 4, 5];

  return (
    <div
      data-map-export-exclude
      className="absolute top-3 left-3 z-10 max-w-[260px] rounded-sm border border-border bg-bg-elevated/95 text-xs shadow-sm"
    >
      <button
        type="button"
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-text-muted hover:text-text"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon size={12} aria-hidden="true" />
        <span className="cp-label">{MAP_COPY.legend}</span>
      </button>
      {open ? (
        <ul className="flex flex-col gap-1.5 border-t border-border px-2.5 py-2 text-text-muted">
          <li className="flex items-center gap-2">
            <Swatch stroke="var(--color-border-strong)" arrow />
            <span className="flex-1">{MAP_COPY.legendImport}</span>
            <InfoTooltip label="What is an import link?" text={TOOLTIPS.mapImportEdge} />
          </li>
          <li className="flex items-center gap-2">
            <Swatch stroke="var(--color-warning)" dashed />
            <span className="flex-1">{MAP_COPY.legendHidden}</span>
            <InfoTooltip label="What is a hidden link?" text={TOOLTIPS.mapHiddenEdge} />
          </li>
          <li className="flex items-center gap-2">
            <Swatch stroke="var(--color-danger)" arrow />
            <span className="flex-1">{MAP_COPY.legendCycle}</span>
            <InfoTooltip label="What is a cycle link?" text={TOOLTIPS.mapCycleEdge} />
          </li>
          <li className="flex items-center gap-2">
            <span className="w-7 shrink-0 text-center text-accent">▲</span>
            <span className="flex-1">{MAP_COPY.legendEntry}</span>
            <InfoTooltip label="What is an entry point?" text={TOOLTIPS.entryPoint} />
          </li>
          {activityOn ? (
            <li className="flex flex-col gap-1 pt-1">
              <div className="flex items-center gap-1.5">
                <span>{MAP_COPY.legendQuiet}</span>
                <span className="flex flex-1 overflow-hidden rounded-xs border border-border">
                  {ramp.map((b) => (
                    <span key={b} className="h-3 flex-1" style={{ background: activityColor(b) }} />
                  ))}
                </span>
                <span>{MAP_COPY.legendBusy}</span>
                <InfoTooltip label="What is activity?" text={TOOLTIPS.mapActivity} />
              </div>
              <span className="text-2xs">{MAP_COPY.legendActivityCaption}</span>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
