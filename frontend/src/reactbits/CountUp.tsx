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
import { animate, useInView, useMotionValue } from "motion/react";
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
    // A fixed-duration tween, not a physics spring -- a spring's time to
    // VISUALLY settle (once its output is rounded/formatted, as every
    // caller here does) grows with the distance travelled, so the same
    // spring constants that read as a brisk ~1s for a small score take
    // 5-8+ seconds to finish counting up a repository's real commit count
    // (thousands). Found via this session's own end-to-end verification --
    // the showcase cards' CountUp numbers were still visibly climbing long
    // after the "one-shot, on enter-view" motion budget (rebuild spec
    // section 6.2) implies they should have settled. `animate()` on the
    // same MotionValue honors `duration` regardless of magnitude.
    const controls = animate(motionValue, to, { duration, ease: "easeOut" });
    return () => controls.stop();
  }, [inView, reducedMotion, to, motionValue, duration, format]);

  useEffect(() => {
    const unsubscribe = motionValue.on("change", (latest) => {
      if (ref.current) ref.current.textContent = format(latest);
    });
    return unsubscribe;
  }, [motionValue, format]);

  return <span ref={ref} className={className} />;
}
