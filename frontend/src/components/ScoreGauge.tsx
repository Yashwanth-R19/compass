import { useRef } from "react";
import { useInView } from "motion/react";
import { healthColor } from "../lib/format";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { CountUp } from "../reactbits/CountUp";

/** The one score ring in the app (Overview's Health Score) -- a singular,
 * never-repeated element, unlike the list rows elsewhere in this app that
 * deliberately keep hover/entrance effects minimal to survive repetition.
 * The ring starts empty and fills to its real value the first time it
 * scrolls into view, matching the same "on enter-view, once" convention
 * `reactbits/CountUp.tsx` already established for every other real metric
 * in the app -- this component's own number now goes through that same
 * CountUp rather than rendering a static digit, closing a gap where the
 * app's single most prominent score was the one number in it that never
 * animated. */
export function ScoreGauge({ score, size = 140 }: { score: number; size?: number }) {
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));
  const colors = healthColor(clamped);

  const reducedMotion = usePrefersReducedMotion();
  const ref = useRef<SVGSVGElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px" });
  const filled = reducedMotion || inView;
  const offset = filled ? circumference * (1 - clamped / 100) : circumference;

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg ref={ref} width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={10}
          fill="none"
          className="stroke-border"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={10}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={`transition-[stroke-dashoffset] duration-[var(--dur-slow)] ease-[var(--ease-out)] motion-reduce:transition-none ${colors.ring}`}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className={`cp-stat text-3xl font-semibold ${colors.text}`}>
          <CountUp to={Math.round(clamped)} />
        </span>
        <span className="cp-label">/ 100</span>
      </div>
    </div>
  );
}
