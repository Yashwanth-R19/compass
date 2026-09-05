// SOURCE: reactbits.dev — Glare Hover
// Adapted from the stock reactbits.dev/tailwind variant: the stock demo
// hardcodes a fixed 500x500px black card with a white glare. Retinted to
// wrap arbitrary already-styled content (a button, a link) instead of
// replacing its chrome -- `background`/`borderColor` default to
// transparent so it never paints over the wrapped element's own
// background/border, sizing defaults to 100%/100% (fill the wrapper's own
// box) rather than a fixed pixel size, and `glareColor` defaults to a warm
// ivory rather than the stock component's plain white -- a genuine light
// reflection is always LIGHTER than the surface it's on, which is also why
// this can't reuse the gilt-gold accent itself the way SpotlightCard's
// glow does: a same-hue sheen on the app's own solid-gold buttons reads as
// almost no contrast at all (found by screenshotting it -- the first
// attempt at this file used the accent hex and was nearly invisible on the
// primary CTA it was meant to highlight). Gated behind this app's
// prefers-reduced-motion discipline (rule M5) -- under reduced motion the
// sheen never animates in at all, rather than animating instantly.
import { useRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

function toRgba(hexOrColor: string, opacity: number): string {
  const hex = hexOrColor.replace("#", "");
  if (/^[\da-fA-F]{6}$/.test(hex)) {
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${opacity})`;
  }
  return hexOrColor;
}

export function GlareHover({
  children,
  className = "",
  style,
  glareColor = "#fff6e0",
  glareOpacity = 0.55,
  glareAngle = -45,
  glareSize = 250,
  transitionDuration = 650,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  glareColor?: string;
  glareOpacity?: number;
  glareAngle?: number;
  glareSize?: number;
  transitionDuration?: number;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const overlayRef = useRef<HTMLDivElement>(null);
  const rgba = toRgba(glareColor, glareOpacity);

  function animateIn() {
    if (reducedMotion) return;
    const el = overlayRef.current;
    if (!el) return;
    el.style.transition = "none";
    el.style.backgroundPosition = "-100% -100%";
    // Force a reflow so the "none" transition above actually applies
    // before switching back -- otherwise the browser coalesces both style
    // writes into one frame and the sheen never animates in.
    void el.offsetHeight;
    el.style.transition = `background-position ${transitionDuration}ms ease`;
    el.style.backgroundPosition = "100% 100%";
  }

  function animateOut() {
    if (reducedMotion) return;
    const el = overlayRef.current;
    if (!el) return;
    el.style.transition = `background-position ${transitionDuration}ms ease`;
    el.style.backgroundPosition = "-100% -100%";
  }

  return (
    <div
      className={`relative overflow-hidden ${className}`}
      style={style}
      onMouseEnter={animateIn}
      onMouseLeave={animateOut}
    >
      <div className="relative">{children}</div>
      {/* Painted AFTER (not before) `children` -- an opaque button fill
          would otherwise sit on top of this overlay in normal DOM
          stacking order and hide the sheen underneath it entirely. */}
      <div
        ref={overlayRef}
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background: `linear-gradient(${glareAngle}deg, transparent 60%, ${rgba} 70%, transparent 100%)`,
          backgroundSize: `${glareSize}% ${glareSize}%`,
          backgroundRepeat: "no-repeat",
          backgroundPosition: "-100% -100%",
        }}
      />
    </div>
  );
}
