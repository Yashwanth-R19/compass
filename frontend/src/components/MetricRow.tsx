import type { ReactNode } from "react";

/** A compact label/value strip -- used for the tour stop metric row and
 * anywhere else a handful of small stats need to sit on one line without a
 * full <dl> grid (Card's own dl patterns are for a card-sized block; this is
 * for a single inline row inside one). */
export function MetricRow({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5">
          <dt className="cp-label">{item.label}</dt>
          <dd className="cp-stat font-medium text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
