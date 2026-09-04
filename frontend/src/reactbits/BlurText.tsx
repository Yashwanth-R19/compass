// SOURCE: reactbits.dev — BlurText
// Adapted from the stock reactbits.dev/tailwind variant: same
// IntersectionObserver + motion/react keyframe mechanism, retinted (no
// component-local colour of its own — it renders the caller's className),
// with a `tag` prop (Compass needs this as a real `h1`, not a bare `<p>`,
// for the landing hero) and this app's own prefers-reduced-motion
// discipline (rule M5) in place of the stock component's own lack of one —
// the stock version has no reduced-motion guard at all.
import { motion } from "motion/react";
import type { Easing, Transition } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

type Tag = "h1" | "h2";

function buildKeyframes(
  from: Record<string, string | number>,
  steps: Array<Record<string, string | number>>,
): Record<string, Array<string | number>> {
  const keys = new Set<string>([...Object.keys(from), ...steps.flatMap((s) => Object.keys(s))]);
  const keyframes: Record<string, Array<string | number>> = {};
  keys.forEach((k) => {
    keyframes[k] = [from[k], ...steps.map((s) => s[k])];
  });
  return keyframes;
}

const FROM = { filter: "blur(10px)", opacity: 0, y: -30 };
const STEPS = [
  { filter: "blur(4px)", opacity: 0.6, y: 4 },
  { filter: "blur(0px)", opacity: 1, y: 0 },
];
const EASING: Easing = (t: number) => t;

/** Reveals a string word-by-word with a blur-in motion -- the landing
 * hero's one animated title reveal (rebuild spec section 6.2: "landing
 * hero | SplitText or BlurText, ONE of them | once, first load only").
 * Under reduced motion, renders plain text immediately -- no per-word
 * wrapper spans, no animation. */
export function BlurText({
  text,
  tag = "h1",
  className = "",
  delay = 60,
  stepDuration = 0.35,
}: {
  text: string;
  tag?: Tag;
  className?: string;
  delay?: number;
  stepDuration?: number;
}) {
  const words = useMemo(() => text.split(" "), [text]);
  const [inView, setInView] = useState(false);
  const ref = useRef<HTMLHeadingElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (reducedMotion || !ref.current) return;
    const el = ref.current;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.unobserve(el);
        }
      },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [reducedMotion]);

  if (reducedMotion) {
    return tag === "h2" ? (
      <h2 className={className}>{text}</h2>
    ) : (
      <h1 className={className}>{text}</h1>
    );
  }

  const totalDuration = stepDuration * STEPS.length;
  const times = [0, ...STEPS.map((_, i) => (i + 1) / STEPS.length)];
  const MotionTag = tag === "h2" ? motion.h2 : motion.h1;

  return (
    <MotionTag ref={ref} className={`${className} flex flex-wrap`}>
      {words.map((word, index) => {
        const animateKeyframes = buildKeyframes(FROM, STEPS);
        const transition: Transition = {
          duration: totalDuration,
          times,
          delay: (index * delay) / 1000,
          ease: EASING,
        };
        return (
          <motion.span
            key={`${word}-${index}`}
            initial={FROM}
            animate={inView ? animateKeyframes : FROM}
            transition={transition}
            style={{ display: "inline-block", willChange: "transform, filter, opacity" }}
          >
            {word}
            {index < words.length - 1 ? " " : ""}
          </motion.span>
        );
      })}
    </MotionTag>
  );
}
