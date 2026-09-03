import type { CSSProperties } from "react";

/** A loading placeholder shaped like what it becomes -- callers pass real
 * dimensions rather than reaching for one generic block everywhere. A soft
 * pulse, not a shimmer sweep, and it still respects
 * `prefers-reduced-motion` via index.css's global override. */
export function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return (
    <div
      className={`animate-pulse rounded-sm bg-bg-inset ${className}`}
      style={style}
      aria-hidden="true"
    />
  );
}

/** A skeleton line matching a text row's height/width -- the common case
 * shouldn't need a bespoke className every time. */
export function SkeletonText({
  width = "100%",
  className = "",
}: {
  width?: string;
  className?: string;
}) {
  return <Skeleton className={`h-3.5 ${className}`} style={{ width }} />;
}
