import { motion, useInView } from "motion/react";
import { useRef } from "react";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";

type Tag = "h1" | "h2";

/**
 * Reveals a display-serif string WORD BY WORD, each word fading up with a
 * staggered delay -- deliberately not a letter-level or blur-based reveal
 * (rule M4 / rebuild spec section 2.2: this is the one place Compass must
 * NOT resemble the reference product's letter-blur wordmark animation).
 * Used for the landing wordmark (this session) and, in session 2, the two
 * narrative page titles.
 *
 * Rule M5: checks reduced motion itself -- under reduced motion this
 * renders plain text, no per-word wrapper spans, no animation.
 */
export function WordReveal({
  text,
  tag = "h1",
  className = "",
  delayStep = 0.06,
  startDelay = 0,
}: {
  text: string;
  tag?: Tag;
  className?: string;
  delayStep?: number;
  startDelay?: number;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  const inView = useInView(ref, { once: true });
  const reducedMotion = usePrefersReducedMotion();
  const words = text.split(" ");

  if (reducedMotion) {
    const Tag = tag;
    return <Tag className={className}>{text}</Tag>;
  }

  const MotionTag = tag === "h2" ? motion.h2 : motion.h1;

  return (
    <MotionTag ref={ref} className={className}>
      {words.map((word, i) => (
        <motion.span
          key={`${word}-${i}`}
          className="inline-block"
          initial={{ opacity: 0, y: 14 }}
          animate={inView ? { opacity: 1, y: 0 } : undefined}
          transition={{
            duration: 0.5,
            delay: startDelay + i * delayStep,
            ease: [0.22, 0.61, 0.36, 1],
          }}
        >
          {word}
          {i < words.length - 1 ? " " : ""}
        </motion.span>
      ))}
    </MotionTag>
  );
}
