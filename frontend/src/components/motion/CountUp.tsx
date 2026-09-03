import { useInView, useMotionValue, useSpring } from "motion/react";
import { useCallback, useEffect, useRef } from "react";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";

/**
 * Spring-animates a number from `from` to `to`, once, the first time it
 * scrolls into view -- written by hand (rule, section 3.4/Part E: "do not
 * add a counter dependency"), not ported from a library. Used by the
 * landing page's showcase cards for `commit_count`/`subsystem_count`/
 * `truck_factor`/`health_score`.
 *
 * Rule M5: independently checks reduced motion (the global CSS override in
 * index.css cannot reach a `useSpring`-driven value) -- under reduced
 * motion the final value renders immediately, no animation at all.
 */
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

  // Stable across renders unless decimals/suffix themselves change, so it
  // can sit in each effect's dependency array below without causing an
  // extra re-run every render.
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
