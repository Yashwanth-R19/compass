/**
 * The one categorical colour source for the whole app (rebuild spec
 * section 5.4) -- replaces the deleted `lib/subsystemColors.ts`. Every
 * categorical thing this app colours (a subsystem, a contributor band, a
 * language in a chart) resolves through `colorForKey`, namespacing its own
 * key rather than reaching for a second palette: `colorForKey("contributor:"
 * + name)`, `colorForKey("language:" + lang)`. The same key always produces
 * the same colour everywhere it's used.
 *
 * Aporia's "celestial" set (SKILL.md section 7) -- muted jewel and earth
 * tones, no purple anywhere (rule 1), legible on both the dark and light
 * backgrounds. Scheme-invariant: a subsystem's identity must not change hue
 * between a light- and dark-mode screenshot of the same repo.
 */
const PALETTE: readonly string[] = [
  "#C2703D", // burnt amber
  "#3E6098", // dusty blue
  "#4E7A6B", // sage teal
  "#A03E4C", // muted crimson
  "#8A6D3B", // ochre
  "#5E7C4F", // moss
  "#417D8A", // petrol
  "#B5794E", // clay
  "#556A9E", // slate blue
  "#7A8450", // olive
  "#9C5561", // rosewood
  "#4A8072", // viridian
  "#C79A3E", // gold
  "#8C4A5A", // mulberry
];

const NEUTRAL_DARK = "#525A6B";
const NEUTRAL_LIGHT = "#9A9488";

function currentTheme(): "dark" | "light" {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

/** Deterministic FNV-1a hash -- same key always lands on the same palette
 * slot, in this process and every other one, with no shared mutable state
 * to keep in sync. */
function fnv1a(input: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** `null`/`undefined` (no subsystem, no known category) always resolves to
 * a neutral grey, never a palette slot -- so "unassigned" can never be
 * mistaken for a real, distinct category. */
export function colorForKey(key: string | null | undefined): string {
  if (!key) return currentTheme() === "light" ? NEUTRAL_LIGHT : NEUTRAL_DARK;
  const index = fnv1a(key) % PALETTE.length;
  return PALETTE[index];
}

export { PALETTE as CATEGORICAL_PALETTE };
