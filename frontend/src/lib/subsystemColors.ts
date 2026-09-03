// Session 09, Part A: the ONE palette shared by the codebase map's subsystem
// graph (pages/onboard/MapPage.tsx), its treemap, the 3D code city
// (components/CodeCity.tsx), and the Structure surface's architecture graph
// (pages/repo/StructureSurfacePage.tsx, UI rebuild session 4 -- formerly
// pages/audit/ArchitecturePage.tsx). A subsystem must render as the same
// colour in all four -- otherwise they feel like unrelated apps rather than
// four lenses on the same computed partition.
//
// Session 15: the palette itself now lives in styles/tokens.css
// (`--subsystem-1`..`--subsystem-12`, `--subsystem-unassigned`) and is read
// once by lib/chartTheme.ts -- SEE THAT MODULE for the getComputedStyle
// mechanics and why raw hex still ends up here rather than a CSS variable
// reference (none of the four renderers above read CSS custom properties on
// their own; recharts/canvas/three.js all need a plain string). This module
// stays the ACCESSOR: every consumer keeps calling `colorForSubsystem`
// exactly as before, so moving the palette into tokens was a one-file
// change, not a four-file hunt.
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
// well-separated hue/lightness combinations -- verified this session with a
// programmatic deuteranopia/protanopia simulation, not just by eye (see
// scripts/verify-subsystem-palette.mjs and DESIGN.md's accessibility
// section for the actual pairwise-distance numbers).
import { SUBSYSTEM_PALETTE, UNASSIGNED_COLOR } from "./chartTheme";

export { SUBSYSTEM_PALETTE, UNASSIGNED_COLOR };

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
 * identifier every one of the four renderers' data sources actually
 * carries. `null`/`undefined` (a file with no subsystem) always returns
 * UNASSIGNED_COLOR, never a hashed slot. */
export function colorForSubsystem(key: string | number | null | undefined): string {
  if (key === null || key === undefined || key === "") return UNASSIGNED_COLOR;
  const hash = hashString(String(key));
  return SUBSYSTEM_PALETTE[hash % SUBSYSTEM_PALETTE.length];
}
