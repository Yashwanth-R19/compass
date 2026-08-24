// Session 09, Part A: the ONE palette shared by the codebase map's subsystem
// graph (pages/onboard/MapPage.tsx), its treemap, and the 3D code city
// (components/CodeCity.tsx). A subsystem must render as the same colour in
// all three views -- otherwise the three feel like three unrelated apps
// rather than three lenses on the same computed partition. Session 15 moves
// this into real design tokens; keeping it in one module now is what makes
// that a one-file change instead of a three-file hunt.
//
// HEURISTIC, not locked (plan/RULES.md sec 3): hand-picked, not derived from
// a formula. Both HUE and LIGHTNESS vary across the 12 entries, not hue
// alone -- deuteranopia (the most common form of red-green colour
// blindness) collapses hue discrimination fastest between red and green, so
// relying on hue contrast alone would make several of these look identical
// to a deuteranope. Varying lightness/saturation alongside hue keeps every
// pair distinguishable by luminance contrast even when a hue pair reads as
// similar. Base 7 (minus black, which reads poorly as a small graph node or
// treemap fill against a dark theme) come from Okabe & Ito's published
// colour-blind-safe set; the remaining 5 extend it with additional
// well-separated hue/lightness combinations. This is a good-faith,
// visually-reviewed choice, not verified against an automated CVD simulator.
export const SUBSYSTEM_PALETTE: readonly string[] = [
  "#0072B2", // blue
  "#E69F00", // orange
  "#009E73", // bluish green
  "#CC79A7", // reddish purple
  "#56B4E9", // sky blue
  "#D55E00", // vermillion
  "#F0C808", // gold
  "#7B3294", // purple
  "#994F00", // brown
  "#117733", // dark green (distinct lightness from bluish green above)
  "#88419D", // violet
  "#4D4D4D", // neutral slate
];

/** A file/subsystem with no known subsystem yet (e.g. the "subsystems" stage
 * for this run hasn't finished computing) -- deliberately NOT drawn from
 * SUBSYSTEM_PALETTE, so "unassigned" can never be visually confused with a
 * real, hashed-to-that-slot subsystem. Matches the app's existing neutral
 * (Tailwind slate-400), not a new colour introduced for this module. */
export const UNASSIGNED_COLOR = "#94a3b8";

/** Deterministic 32-bit FNV-1a string hash -- same input always produces the
 * same output, in this process or any other, which is what
 * `colorForSubsystem` needs to satisfy "deterministic" (Part A). */
function hashString(input: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Resolves a subsystem to a colour, deterministically. Accepts either a
 * numeric subsystem id (the /city payload's `subsystem_id`) or a label
 * string (every other endpoint that exposes subsystems -- `/subsystems`,
 * `/module-coupling?granularity=subsystem` -- only ever returns the label,
 * never a numeric id, see CLAUDE.md's "Codebase map" section). Callers that
 * want the SAME subsystem to render identically across more than one view
 * must pass the SAME representation each time -- in practice, resolve to
 * the subsystem's label before calling this, since label is the one
 * identifier every one of the three renderers' data sources actually
 * carries. `null`/`undefined` (a file with no subsystem) always returns
 * UNASSIGNED_COLOR, never a hashed slot. */
export function colorForSubsystem(key: string | number | null | undefined): string {
  if (key === null || key === undefined || key === "") return UNASSIGNED_COLOR;
  const hash = hashString(String(key));
  return SUBSYSTEM_PALETTE[hash % SUBSYSTEM_PALETTE.length];
}
