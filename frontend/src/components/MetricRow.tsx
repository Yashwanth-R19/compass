import type { ReactNode } from "react";

/** A compact label/value strip -- used anywhere a handful of small stats
 * need to sit on one line without a full grid. */
export function MetricRow({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5">
          <dt className="cp-label">{item.label}</dt>
          <dd className="cp-stat font-medium text-text">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
