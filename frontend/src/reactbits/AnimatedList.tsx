// SOURCE: reactbits.dev — AnimatedList
// Adapted from the stock reactbits.dev/tailwind variant: same
// motion/react useInView per-item stagger mechanism, retinted (the stock
// version hardcodes a dark `#111`/`#222` card look; this renders the
// caller's own item markup instead, so Compass's own Card/list styling
// applies), generalised from `items: string[]` to `items: T[]` with a
// `renderItem` callback (every real use in this app -- showcase cards,
// findings, tour stops, contributors -- renders structured content, never
// a bare string), and given this app's own prefers-reduced-motion
// discipline (rule M5) in place of the stock component's keyboard-nav/
// scrollbar-styling extras, which nothing here needs.
import { motion, useInView } from "motion/react";
import { useRef } from "react";
import type { ReactNode } from "react";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

const MAX_STAGGER_ITEMS = 8;
const STAGGER_STEP_S = 0.04;

function AnimatedItem({ children, delay }: { children: ReactNode; delay: number }) {
  const ref = useRef<HTMLLIElement>(null);
  const inView = useInView(ref, { amount: 0.4, once: true });
  return (
    <motion.li
      ref={ref}
      initial={{ opacity: 0, y: 10 }}
      animate={inView ? { opacity: 1, y: 0 } : undefined}
      transition={{ duration: 0.3, delay }}
    >
      {children}
    </motion.li>
  );
}

/** A staggered list reveal (rebuild spec section 6.2: "findings, tour
 * stops, contributors, showcase cards | AnimatedList | stagger <= 40ms,
 * cap the stagger at ~8 items") -- each item fades/rises in as it enters
 * view, once, with the stagger capped so a long list doesn't take
 * noticeably longer to finish appearing than a short one. Under reduced
 * motion, every item renders in its final state immediately. */
export function AnimatedList<T>({
  items,
  renderItem,
  keyFor,
  className = "",
}: {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  keyFor: (item: T, index: number) => string | number;
  className?: string;
}) {
  const reducedMotion = usePrefersReducedMotion();

  if (reducedMotion) {
    return (
      <ul className={className}>
        {items.map((item, i) => (
          <li key={keyFor(item, i)}>{renderItem(item, i)}</li>
        ))}
      </ul>
    );
  }

  return (
    <ul className={className}>
      {items.map((item, i) => (
        <AnimatedItem key={keyFor(item, i)} delay={Math.min(i, MAX_STAGGER_ITEMS) * STAGGER_STEP_S}>
          {renderItem(item, i)}
        </AnimatedItem>
      ))}
    </ul>
  );
}
