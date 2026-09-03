import { motion, useInView } from "motion/react";
import { useRef } from "react";
import type { ReactNode, Ref } from "react";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";

/**
 * The one general-purpose entrance reveal (rule M4): a one-shot fade-up
 * (opacity 0 -> 1, translateY 12px -> 0) fired the first time the element
 * enters the viewport, never again. `delay` (seconds) is what lets a
 * caller stagger several `Reveal`s by index for one orchestrated section
 * entrance (rule M1: one orchestrated reveal per view, not many scattered
 * effects) rather than each one firing independently.
 *
 * Rule M5: checks reduced motion itself (index.css's global CSS override
 * does not reach a JS-driven `motion` animation) -- under reduced motion
 * this renders `children` directly, with no motion wrapper element at all,
 * so there is nothing to ever animate.
 */
export function Reveal({
  children,
  delay = 0,
  className = "",
  as = "div",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "li";
}) {
  // A single ref shared by both possible tags -- useInView only needs an
  // Element, and the two branches below each cast it to the specific tag
  // they render (never both at once, so this is safe).
  const ref = useRef<HTMLDivElement | HTMLLIElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -10% 0px" });
  const reducedMotion = usePrefersReducedMotion();

  if (reducedMotion) {
    return as === "li" ? (
      <li className={className}>{children}</li>
    ) : (
      <div className={className}>{children}</div>
    );
  }

  const initial = { opacity: 0, y: 12 };
  const transition = { duration: 0.62, delay, ease: [0.22, 0.61, 0.36, 1] as const };

  return as === "li" ? (
    <motion.li
      ref={ref as Ref<HTMLLIElement>}
      className={className}
      initial={initial}
      animate={inView ? { opacity: 1, y: 0 } : undefined}
      transition={transition}
    >
      {children}
    </motion.li>
  ) : (
    <motion.div
      ref={ref as Ref<HTMLDivElement>}
      className={className}
      initial={initial}
      animate={inView ? { opacity: 1, y: 0 } : undefined}
      transition={transition}
    >
      {children}
    </motion.div>
  );
}
