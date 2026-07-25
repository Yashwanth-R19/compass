import { useEffect, useRef, useState } from "react";

const DEFAULT_HEIGHT = 520;

/** Measures its own width via ResizeObserver so the wrapped force-graph gets
 * real pixel dimensions instead of guessing -- react-force-graph-2d needs an
 * explicit width/height, it doesn't fill its container on its own. */
export function GraphCanvas({
  height = DEFAULT_HEIGHT,
  children,
}: {
  height?: number;
  children: (size: { width: number; height: number }) => React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={containerRef}
      className="w-full overflow-hidden rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950/40"
      style={{ height }}
    >
      {width > 0 ? children({ width, height }) : null}
    </div>
  );
}
