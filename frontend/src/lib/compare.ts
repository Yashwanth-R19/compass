// Pure helpers for the run-vs-run compare page (session 13, Part G) --
// "deltas must be visually directional... the UI must know which" (a -12 is
// good for risk-shaped metrics, bad for truck-factor-shaped ones). Kept
// separate from the page component so the direction logic is independently
// testable without rendering anything.
import type { HeadlineDeltaOut } from "../api/types";

export type DeltaDirection = "improved" | "worsened" | "neutral";

/** `higher_is_better` (server-supplied, per metric -- app/schemas/compare.py)
 * is the ONE thing this needs: `null` means the metric has no inherent
 * direction (e.g. subsystem_count), a zero/null delta is always neutral. */
export function headlineDirection(item: HeadlineDeltaOut): DeltaDirection {
  if (item.delta === null || item.delta === 0 || item.higher_is_better === null) {
    return "neutral";
  }
  const improved = item.higher_is_better ? item.delta > 0 : item.delta < 0;
  return improved ? "improved" : "worsened";
}

// Reads the dedicated diverging pair (tokens.css's --color-diverging-*,
// section 3.1: verdigris is the positive hue, R1 -- there is no separate
// green in this system) rather than a raw emerald/red pair, so a compare
// delta's colouring agrees with every other accent/warning use in the app.
export const DIRECTION_TEXT_CLASS: Record<DeltaDirection, string> = {
  improved: "text-diverging-improve",
  worsened: "text-diverging-worsen",
  neutral: "text-diverging-neutral",
};

export function formatSignedDelta(delta: number): string {
  // `Math.round(-0.002 * 100) / 100` produces JS negative zero, which some
  // engines render as the literal string "-0" via toLocaleString() -- found
  // during manual QA (a genuinely tiny negative health-score delta rendered
  // as a bare "-0" instead of "0"). `+ 0` normalizes -0 to 0 before display.
  const rounded = (Number.isInteger(delta) ? delta : Math.round(delta * 100) / 100) + 0;
  return rounded > 0 ? `+${rounded.toLocaleString()}` : rounded.toLocaleString();
}
