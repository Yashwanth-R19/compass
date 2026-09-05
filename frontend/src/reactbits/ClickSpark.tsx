// SOURCE: reactbits.dev — Click Spark
// Adapted from the stock reactbits.dev/tailwind variant (the metadata
// lists framer-motion as a dependency; the actual source imports nothing
// but React -- a plain canvas + requestAnimationFrame loop). `sparkColor`
// defaults to a warm ivory (a literal hex, not a `var(--cp-accent)`
// reference -- a <canvas> stroke colour can't resolve a CSS custom
// property, and a value this short-lived, 400ms, doesn't need to track a
// live theme switch) rather than the app's own gold accent: the accent is
// also this app's solid button fill colour, and a same-hue spark on a
// same-hue button is nearly invisible -- found by screenshotting the first
// attempt at this file, same lesson reactbits/GlareHover.tsx's own comment
// documents. Given this app's own prefers-reduced-motion discipline (rule
// M5: every motion primitive gates itself independently in JS, not just
// via the global CSS rule), reduced motion disables the spark burst
// entirely -- the wrapped button/link still receives the click normally
// either way.
import { useCallback, useEffect, useRef } from "react";
import type { MouseEvent, ReactNode } from "react";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

interface Spark {
  x: number;
  y: number;
  angle: number;
  startTime: number;
}

export function ClickSpark({
  children,
  sparkColor = "#fff6e0",
  sparkSize = 8,
  sparkRadius = 16,
  sparkCount = 8,
  duration = 400,
  className = "",
}: {
  children: ReactNode;
  sparkColor?: string;
  sparkSize?: number;
  sparkRadius?: number;
  sparkCount?: number;
  duration?: number;
  className?: string;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sparksRef = useRef<Spark[]>([]);

  useEffect(() => {
    if (reducedMotion) return;
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    let resizeTimeout: ReturnType<typeof setTimeout>;
    const resizeCanvas = () => {
      const { width, height } = parent.getBoundingClientRect();
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
    };
    const ro = new ResizeObserver(() => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(resizeCanvas, 100);
    });
    ro.observe(parent);
    resizeCanvas();

    const ctx = canvas.getContext("2d");
    let animationId: number;
    const ease = (t: number) => t * (2 - t);

    const draw = (timestamp: number) => {
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      sparksRef.current = sparksRef.current.filter((spark) => {
        const elapsed = timestamp - spark.startTime;
        if (elapsed >= duration) return false;

        const eased = ease(elapsed / duration);
        const distance = eased * sparkRadius;
        const lineLength = sparkSize * (1 - eased);
        const x1 = spark.x + distance * Math.cos(spark.angle);
        const y1 = spark.y + distance * Math.sin(spark.angle);
        const x2 = spark.x + (distance + lineLength) * Math.cos(spark.angle);
        const y2 = spark.y + (distance + lineLength) * Math.sin(spark.angle);

        ctx.strokeStyle = sparkColor;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        return true;
      });
      animationId = requestAnimationFrame(draw);
    };
    animationId = requestAnimationFrame(draw);

    return () => {
      ro.disconnect();
      clearTimeout(resizeTimeout);
      cancelAnimationFrame(animationId);
    };
  }, [reducedMotion, sparkColor, sparkSize, sparkRadius, duration]);

  const handleClick = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (reducedMotion) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const now = performance.now();
      sparksRef.current.push(
        ...Array.from({ length: sparkCount }, (_, i) => ({
          x,
          y,
          angle: (2 * Math.PI * i) / sparkCount,
          startTime: now,
        })),
      );
    },
    [reducedMotion, sparkCount],
  );

  return (
    <div className={`relative ${className}`} onClick={handleClick}>
      {children}
      {/* Painted AFTER (not before) `children` -- an opaque button fill
          would otherwise sit on top of the canvas in normal DOM stacking
          order and hide every spark drawn underneath it. */}
      {reducedMotion ? null : (
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0" />
      )}
    </div>
  );
}
