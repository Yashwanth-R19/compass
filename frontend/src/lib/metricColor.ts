// Shared colour-scale helpers for the non-subsystem colour modes (risk,
// principal owner, recency of last change) used by BOTH the codebase map
// (pages/onboard/MapPage.tsx, Part C) and the 3D code city
// (components/CodeCity.tsx, Part F) -- the same reasoning that keeps
// subsystem colours in ONE module (subsystemColors.ts) applies here:
// "risk" must look like the same risk gradient in both views, not two
// independently tuned scales that happen to share a name.
//
// Session 15: RISK_LOW/RISK_HIGH/RECENCY_FRESH/RECENCY_STALE and the lerp
// machinery now live in lib/chartTheme.ts (the single source for all four
// renderers -- recharts, the force graph, the treemap, and the 3D city; see
// that module's own docstring). This module stays the map/city-specific
// ACCESSOR layer (riskColor/recencyColor/ownerColor), re-exported from
// there rather than redefining a second copy of the same scale.
import { colorForSubsystem, UNASSIGNED_COLOR } from "./subsystemColors";
import { lerpColor, RECENCY_FRESH, riskScaleColor } from "./chartTheme";

export { lerpColor, RECENCY_FRESH };
export const RECENCY_STALE = UNASSIGNED_COLOR;

export function average(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

/** Most frequent non-null/undefined value; ties broken by first-seen order
 * (Map iteration order == insertion order), so this is deterministic for a
 * given input, not dependent on incidental value ordering. Used for both
 * "majority subsystem" and "majority owner" when aggregating a directory or
 * a collapsed subsystem's files into one representative colour. */
export function majority<T>(values: (T | null | undefined)[]): T | null {
  const counts = new Map<T, number>();
  for (const v of values) {
    if (v === null || v === undefined) continue;
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  let best: T | null = null;
  let bestCount = 0;
  for (const [v, count] of counts) {
    if (count > bestCount) {
      best = v;
      bestCount = count;
    }
  }
  return best;
}

/** 0 (lowest) .. 1 (highest), across chartTheme's six-stop heat ramp --
 * `score` is already the [0,1]-scaled risk_score every risk-related
 * response already carries, never rescaled here. */
export function riskColor(score: number | null | undefined): string {
  return score == null ? UNASSIGNED_COLOR : riskScaleColor(score);
}

/** `min`/`max` should always come from the server-computed CityBounds
 * (Part E: "the client never derives its own scale"), never computed
 * client-side from a partial or filtered view of the data. */
export function recencyColor(value: number | null | undefined, min: number, max: number): string {
  if (value == null || max === min) return UNASSIGNED_COLOR;
  return lerpColor(RECENCY_STALE, RECENCY_FRESH, (value - min) / (max - min));
}

/** Reuses the SAME categorical palette/hash subsystemColors.ts uses, under
 * a namespaced key ("owner:<id>") so an owner id can never collide with a
 * subsystem label's hash slot by coincidence. Not a second palette -- one
 * hash function, one 12-colour set, two different key namespaces. */
export function ownerColor(contributorId: number | null | undefined): string {
  return contributorId == null ? UNASSIGNED_COLOR : colorForSubsystem(`owner:${contributorId}`);
}
