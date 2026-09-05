// SOURCE: reactbits.dev — Magnet
// Adapted from the stock reactbits.dev/tailwind variant: no colours to
// retint (it's a pure transform wrapper), but the stock version has no
// prefers-reduced-motion awareness at all -- this app's own motion
// discipline (rule M5, `usePrefersReducedMotion`) requires every
// non-essential motion effect to have an off switch, so the magnetic pull
// is forced off (position pinned at the wrapped element's natural spot)
// whenever the OS setting is on, regardless of the caller's own `disabled`
// prop.
import { useEffect, useRef, useState } from "react";
import type { HTMLAttributes, ReactNode } from "react";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

interface MagnetProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  padding?: number;
  disabled?: boolean;
  magnetStrength?: number;
  wrapperClassName?: string;
  innerClassName?: string;
}

/** Wraps `children` (typically one button/link) so it visibly "pulls"
 * toward the cursor within `padding` px of its edges, then eases back once
 * the cursor leaves -- a tasteful, small-radius version of the effect (the
 * default `padding`/`magnetStrength` keep the pull subtle, a few pixels at
 * most, not a cartoonish snap). */
export function Magnet({
  children,
  padding = 60,
  disabled = false,
  magnetStrength = 6,
  wrapperClassName = "",
  innerClassName = "",
  ...props
}: MagnetProps) {
  const reducedMotion = usePrefersReducedMotion();
  const isDisabled = disabled || reducedMotion;
  const [isActive, setIsActive] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isDisabled) {
      setPosition({ x: 0, y: 0 });
      return;
    }

    function handleMouseMove(e: MouseEvent) {
      if (!ref.current) return;
      const { left, top, width, height } = ref.current.getBoundingClientRect();
      const centerX = left + width / 2;
      const centerY = top + height / 2;
      const distX = Math.abs(centerX - e.clientX);
      const distY = Math.abs(centerY - e.clientY);

      if (distX < width / 2 + padding && distY < height / 2 + padding) {
        setIsActive(true);
        setPosition({
          x: (e.clientX - centerX) / magnetStrength,
          y: (e.clientY - centerY) / magnetStrength,
        });
      } else {
        setIsActive(false);
        setPosition({ x: 0, y: 0 });
      }
    }

    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [padding, isDisabled, magnetStrength]);

  return (
    <div
      ref={ref}
      className={wrapperClassName}
      style={{ position: "relative", display: "inline-block" }}
      {...props}
    >
      <div
        className={innerClassName}
        style={{
          transform: `translate3d(${position.x}px, ${position.y}px, 0)`,
          transition: isActive ? "transform 0.2s ease-out" : "transform 0.4s ease-in-out",
          willChange: "transform",
        }}
      >
        {children}
      </div>
    </div>
  );
}
