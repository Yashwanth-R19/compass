import type { ReactNode } from "react";
import { InfoTooltip } from "./ui/InfoTooltip";
import { TOOLTIPS } from "../content/explainability";
import type { TooltipKey } from "../content/explainability";

/** A compact label/value strip -- used anywhere a handful of small stats
 * need to sit on one line without a full grid. An item's `tooltip` (a
 * `content/explainability.ts` key) is optional -- most callers show a
 * self-explanatory raw count (LOC, in-degree) with no tooltip at all;
 * pass one only for a genuinely explainable quantity (section 5.1). */
export function MetricRow({
  items,
}: {
  items: { label: string; value: ReactNode; tooltip?: TooltipKey }[];
}) {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5">
          <dt className="cp-label flex items-center gap-1">
            {item.label}
            {item.tooltip ? (
              <InfoTooltip label={`What is ${item.label}?`} text={TOOLTIPS[item.tooltip]} />
            ) : null}
          </dt>
          <dd className="cp-stat font-medium text-text">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
