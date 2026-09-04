// SOURCE: reactbits.dev — CountUp
// Adapted from the stock reactbits.dev/tailwind variant: rebuilt on the
// same motion/react useMotionValue + useSpring + useInView mechanism, with
// `decimals`/`suffix` (Compass renders scores and percentages, not just
// bare integers) and this app's own prefers-reduced-motion discipline
// (rule M5 -- checked here directly, since the global CSS override in
// index.css cannot reach a JS-driven spring) in place of the stock
// component's `separator`/`direction` props, which nothing in this app
// needs. Retinted is not applicable -- this component renders no colour of
// its own, only a `className` the caller supplies.
import { useInView, useMotionValue, useSpring } from "motion/react";
import { useCallback, useEffect, useRef } from "react";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

/** Spring-animates a number from `from` to `to`, once, the first time it
 * scrolls into view. Every real metric on this app's landing page,
 * showcase cards, and repo surfaces goes through this one component
 * (rebuild spec section 6.2: "every real metric | CountUp | on enter-view,
 * once"). */
export function CountUp({
  to,
  from = 0,
  decimals = 0,
  suffix = "",
  duration = 1.2,
  className = "",
}: {
  to: number;
  from?: number;
  decimals?: number;
  suffix?: string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px" });
  const reducedMotion = usePrefersReducedMotion();

  const motionValue = useMotionValue(from);
  const springValue = useSpring(motionValue, {
    damping: 20 + 40 / duration,
    stiffness: 100 / duration,
  });

  const format = useCallback(
    (value: number): string =>
      value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }) + suffix,
    [decimals, suffix],
  );

  // Paints the starting value immediately on mount, before anything has
  // scrolled into view.
  useEffect(() => {
    if (ref.current) ref.current.textContent = format(from);
  }, [format, from]);

  useEffect(() => {
    if (!inView) return;
    if (reducedMotion) {
      if (ref.current) ref.current.textContent = format(to);
      return;
    }
    motionValue.set(to);
  }, [inView, reducedMotion, to, motionValue, format]);

  useEffect(() => {
    const unsubscribe = springValue.on("change", (latest) => {
      if (ref.current) ref.current.textContent = format(latest);
    });
    return unsubscribe;
  }, [springValue, format]);

  return <span ref={ref} className={className} />;
}
