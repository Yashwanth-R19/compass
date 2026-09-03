import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { SUBSYSTEM_PALETTE, UNASSIGNED_COLOR } from "./chartTheme";
import { colorForSubsystem, SUBSYSTEM_PALETTE as ACCESSOR_PALETTE } from "./subsystemColors";

// Reads real source/CSS files straight off disk via `fs`, deliberately NOT
// Vite's `?raw` import suffix: the `@tailwindcss/vite` plugin transforms
// EVERY `.css` file reachable from the Tailwind import graph regardless of
// a `?raw` query (it has no reason to special-case that suffix away), so a
// `?raw` import of styles/tokens.css silently resolves to an EMPTY string
// under this project's Vite config -- confirmed directly while writing this
// test, not assumed. `fs.readFileSync` bypasses the bundler entirely, which
// is what makes this test actually read the file it claims to.
const THIS_DIR = path.dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = path.join(THIS_DIR, "..");

function readSource(relPath: string): string {
  return readFileSync(path.join(SRC_ROOT, relPath), "utf8");
}

// Session 15, Part F: "assert the subsystem palette exported from
// chartTheme is the one used by the force graph, the treemap, the city
// layout and the Audit architecture view. Import all four and assert
// identity." colorForSubsystem (subsystemColors.ts) is the ONE accessor
// every one of those four call sites uses -- this test checks both ends of
// that chain: that subsystemColors.ts's own palette IS chartTheme's (not a
// second copy), and that each of the four renderer files actually goes
// through that accessor rather than defining its own hardcoded palette.
describe("chartTheme subsystem palette anti-drift", () => {
  it("subsystemColors.ts re-exports chartTheme's exact palette array (same values, not a second copy)", () => {
    expect(ACCESSOR_PALETTE).toEqual(SUBSYSTEM_PALETTE);
  });

  it("colorForSubsystem always resolves into chartTheme's own SUBSYSTEM_PALETTE", () => {
    for (const label of ["billing", "auth", "core", "web", "graph-engine"]) {
      expect(SUBSYSTEM_PALETTE).toContain(colorForSubsystem(label));
    }
  });

  it("has exactly 12 distinct colours, none equal to the unassigned colour", () => {
    expect(SUBSYSTEM_PALETTE.length).toBe(12);
    expect(new Set(SUBSYSTEM_PALETTE).size).toBe(12);
    expect(SUBSYSTEM_PALETTE).not.toContain(UNASSIGNED_COLOR);
  });

  // Source-text scan (the same style of guard session 12's
  // test_narrative_factpack.py uses for its import-path check, and
  // lib/copy.test.ts uses for its exhaustiveness list): each of the
  // renderers must import the shared accessor rather than defining its own
  // hex palette. A file that starts hardcoding `#rrggbb` categorical arrays
  // again is exactly the drift this test exists to catch.
  //
  // UI rebuild session 4 update: the former `pages/audit/CouplingPage.tsx`
  // and `pages/audit/ArchitecturePage.tsx` (two separate files, two
  // separate RENDERERS entries) were deleted and merged into ONE file,
  // `pages/repo/StructureSurfacePage.tsx` (Part C), which contains both the
  // former Coupling view's force graph and the former Architecture view's
  // graph. Collapsed to one entry rather than kept as two pointing at the
  // same path -- a rewrite genuinely required this change (the two old
  // paths no longer exist on disk at all), not a silent behaviour change;
  // see DESIGN_NOTES.md's session 4 entry.
  const RENDERERS: { label: string; path: string }[] = [
    {
      label: "Structure surface (architecture + coupling views)",
      path: "pages/repo/StructureSurfacePage.tsx",
    },
    { label: "treemap (codebase map)", path: "pages/onboard/MapPage.tsx" },
    { label: "city layout (3D city)", path: "components/CodeCity.tsx" },
  ];

  for (const { label, path: relPath } of RENDERERS) {
    it(`${label} (${relPath}) imports colorForSubsystem from lib/subsystemColors, not a local palette`, () => {
      const src = readSource(relPath);
      expect(src).toMatch(/colorForSubsystem/);
      expect(src).toMatch(/from ["'].*subsystemColors["']/);
    });
  }

  it("DirectoryTreemap (the shared treemap component the map/city fallback both use) never hardcodes a categorical hex array", () => {
    const src = readSource("components/DirectoryTreemap.tsx");
    // DirectoryTreemap takes colour as a prop per node rather than deriving
    // it, so there should be no hex literal here at all.
    expect(src).not.toMatch(/#[0-9a-fA-F]{6}/);
  });
});

// UI rebuild session 1: rewritten from "design token light/dark
// completeness" to match tokens.css's new theme architecture. The outgoing
// version anchored on `@media (prefers-color-scheme: dark) { :root { ... } }`
// -- that block no longer exists at all, by design (rebuild spec decision
// #9: dark is the unconditional :root default, with NO
// prefers-color-scheme fallback for the initial theme; light is the one
// applied under `:root[data-theme="light"]`). This is exactly the "a
// rewrite genuinely requires changing behaviour" case the session rules
// anticipate -- the STRUCTURE changed (which block is the base, which is
// the anchored override), but the underlying property this test protects
// (a token declared in one scheme having a matching declaration in the
// other, so it can never silently fall back to an unstyled value) is
// preserved verbatim, just checked against the new anchor. See
// DESIGN_NOTES.md for this session's own note on the change.
describe("design token light/dark completeness", () => {
  const css = readSource("styles/tokens.css");

  // Finds the span of the FIRST top-level block opened by `anchor` (brace
  // depth-matched, so nested braces inside it don't confuse the end).
  function blockSpan(source: string, anchor: RegExp): [number, number] {
    const match = anchor.exec(source);
    if (!match) throw new Error(`Could not find block for ${anchor}`);
    const start = match.index + match[0].length;
    let depth = 1;
    let i = start;
    while (depth > 0 && i < source.length) {
      if (source[i] === "{") depth++;
      if (source[i] === "}") depth--;
      i++;
    }
    return [start, i - 1];
  }

  function tokenNames(cssText: string): string[] {
    const names = new Set<string>();
    const re = /(--cp-[a-z0-9-]+)\s*:/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(cssText))) names.add(m[1]);
    return [...names];
  }

  // The light-mode override block (`:root[data-theme="light"] { ... }`) is
  // now the one unambiguous anchor -- extracting IT first, then treating
  // everything OUTSIDE its span as "dark" (the base :root declarations),
  // sidesteps needing a second, position-fragile anchor to find the base
  // block specifically. `--cp-*` DECLARATIONS (as opposed to `var(--cp-*)`
  // references, which this token scan's `--cp-x:` pattern does not match)
  // only ever appear in that one light block among the non-light text, so
  // scanning the whole non-light remainder is equivalent to scanning just
  // the base :root block.
  const [lightStart, lightEnd] = blockSpan(css, /:root\[data-theme=["']light["']\]\s*{/);
  const lightBlock = css.slice(lightStart, lightEnd);
  const darkText = css.slice(0, lightStart) + css.slice(lightEnd);

  const darkTokens = tokenNames(darkText);
  const lightTokens = tokenNames(lightBlock);

  it("the light-mode override block anchor (the actual rule, not prose mentioning it) appears exactly once", () => {
    const anchor = /:root\[data-theme=["']light["']\]\s*{/g;
    const occurrences = [...css.matchAll(anchor)].length;
    expect(occurrences).toBe(1);
  });

  it("found a non-trivial number of semantic tokens to check", () => {
    expect(darkTokens.length).toBeGreaterThan(15);
  });

  it("every dark-mode (base :root) --cp-* token has a light-mode override", () => {
    const missing = darkTokens.filter((name) => !lightTokens.includes(name));
    expect(missing).toEqual([]);
  });

  it("every light-mode --cp-* token has a dark-mode (base :root) definition (no orphaned light-only token)", () => {
    const missing = lightTokens.filter((name) => !darkTokens.includes(name));
    expect(missing).toEqual([]);
  });

  it("the subsystem categorical palette is scheme-invariant by design (declared once, no light override)", () => {
    // Documented deliberately in tokens.css: a subsystem's colour identity
    // must not change between light and dark screenshots of the same repo.
    expect(lightBlock).not.toMatch(/--subsystem-\d+:/);
  });
});
