// SOURCE: reactbits.dev — Spotlight Card
// Adapted from the stock reactbits.dev/tailwind variant: the stock
// component hardcodes its own card chrome (`rounded-3xl border-neutral-800
// bg-neutral-900 p-8`) and a plain white glow. Retinted to compose with
// Compass's own `Card`/list styling instead of replacing it -- this renders
// nothing of its own but a `position:relative` wrapper and the glow layer,
// so a caller passes its usual card classes (border/bg/radius/padding)
// through `className` rather than getting a second, competing set. The
// glow itself uses the accent gold hue at low opacity rather than the
// stock's plain white, since a white radial glow reads as a UI bug on the
// Parchment Journal (light) theme -- gold reads as an intentional highlight
// in both themes.
import { useRef, useState } from "react";
import type { PropsWithChildren, ReactNode } from "react";

interface Position {
  x: number;
  y: number;
}

const DEFAULT_SPOTLIGHT = "rgba(214, 172, 77, 0.16)";

export function SpotlightCard({
  children,
  className = "",
  spotlightColor = DEFAULT_SPOTLIGHT,
}: PropsWithChildren<{
  className?: string;
  spotlightColor?: string;
}>): ReactNode {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<Position>({ x: 0, y: 0 });
  const [opacity, setOpacity] = useState(0);

  return (
    <div
      ref={ref}
      onMouseMove={(e) => {
        if (!ref.current) return;
        const rect = ref.current.getBoundingClientRect();
        setPosition({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      }}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      className={`relative overflow-hidden ${className}`}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 transition-opacity duration-300 ease-out"
        style={{
          opacity,
          background: `radial-gradient(280px circle at ${position.x}px ${position.y}px, ${spotlightColor}, transparent 70%)`,
        }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}
