// Shared colour-scale helpers for the non-subsystem colour modes (risk,
// principal owner, recency of last change) used by BOTH the codebase map
// (pages/onboard/MapPage.tsx, Part C) and the 3D code city
// (components/CodeCity.tsx, Part F) -- the same reasoning that keeps
// subsystem colours in ONE module (subsystemColors.ts) applies here:
// "risk" must look like the same risk gradient in both views, not two
// independently tuned scales that happen to share a name.
//
// Every base colour here is already used elsewhere in this app for the same
// meaning, not introduced fresh: emerald/red are this app's existing
// healthy/high-severity colours (lib/format.ts::healthColor,
// SEVERITY_CLASSES.high); sky-500 is already used for "selected"
// (ArchitecturePage); the "stale"/"unassigned" neutral is the same
// UNASSIGNED_COLOR subsystemColors.ts already defines.
import { colorForSubsystem, UNASSIGNED_COLOR } from "./subsystemColors";

export const RISK_LOW = "#22c55e"; // emerald-500
export const RISK_HIGH = "#ef4444"; // red-500
export const RECENCY_STALE = UNASSIGNED_COLOR; // slate-400
export const RECENCY_FRESH = "#0ea5e9"; // sky-500

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function toHexByte(v: number): string {
  return Math.round(Math.max(0, Math.min(255, v)))
    .toString(16)
    .padStart(2, "0");
}

/** Linear RGB interpolation between two `#rrggbb` colours, clamped to
 * [0, 1]. Deterministic and pure -- reused by both the map and the city so
 * a given (colour mode, value) always renders identically in each. */
export function lerpColor(colorA: string, colorB: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(colorA);
  const [br, bg, bb] = hexToRgb(colorB);
  const clamped = Math.max(0, Math.min(1, t));
  return `#${toHexByte(ar + (br - ar) * clamped)}${toHexByte(ag + (bg - ag) * clamped)}${toHexByte(ab + (bb - ab) * clamped)}`;
}

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

/** 0 (RISK_LOW) .. 1 (RISK_HIGH) -- `score` is already the [0,1]-scaled
 * risk_score every risk-related response already carries, never rescaled
 * here. */
export function riskColor(score: number | null | undefined): string {
  return score == null ? UNASSIGNED_COLOR : lerpColor(RISK_LOW, RISK_HIGH, score);
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
