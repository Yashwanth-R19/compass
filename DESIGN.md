# Compass design system — "Verdigris & Bone"

UI rebuild session 1's deliverable: a new visual identity for Compass,
replacing session 15's "an instrument, not a dashboard" system. This
document is the reference for the new identity — what it is, why, and the
measured numbers behind the accessibility claims — following the same
discipline the outgoing document established: numbers are measured with
the real formula, not eyeballed, and a hazard that was found and fixed is
recorded here rather than silently corrected.

Read `plan/UI_REBUILD_SESSIONS.md` sections 1-6 for the full normative spec
this document implements — the palette, type scale, spacing, and every hard
rule (V1-V7, M1-M5) are defined there and are not repeated verbatim here
except where needed to explain a decision.

## The direction

**Oxidised copper on warm near-black.** An aged brass field instrument —
still a measurement device, not a SaaS dashboard, but warmer and more
editorial than the outgoing graphite-and-cyan system. Concretely:

- **A real display serif (Newsreader) for headings, a real monospace
  (JetBrains Mono) for measurements**, replacing the outgoing system's
  "Inter for everything, tabular-nums does the work" approach. Body copy
  and UI chrome stay on Inter.
- **Colour encodes data and nothing else.** Severity, risk, confidence,
  subsystem identity, compare direction get colour. Chrome (nav, panels,
  borders, buttons) stays neutral in both schemes. The single exception is
  `--color-accent` (verdigris), reserved for focus rings, the one primary
  call-to-action per page, links, and "selected" chrome.
- **Softened corners and real, restrained shadows** — a deliberate,
  visible departure from the outgoing flat 0-2px/zero-shadow scale (section
  3.3's own framing: "a deliberate, visible departure").
- **Reference point:** an aged brass field instrument's control panel —
  still dense and precise, but warmer and with more typographic
  personality than a terminal/Bloomberg-panel aesthetic.

**Explicitly rejected** (rule V1-V3): purple/violet anywhere, emoji as
iconography (lucide-react only), gradient blobs, glassmorphism, neon glow
(the 3D city's own lighting remains the sole, unchanged exception).

### Rules R1/R2 — why the heat ramp is warm, not red-green

The accent hue is green (verdigris), which forces two structural rules
that shape everything severity/risk-shaped in this system:

- **R1.** Verdigris is the positive hue — `--color-success` deliberately
  sits in the accent family (healthy *is* patina). There is no separate
  "success green" distinct from the accent.
- **R2.** No severity/risk/confidence scale may use green at any stop —
  every such scale runs the six-stop heat ramp (neutral → straw → ochre →
  clay → oxblood → deep), a warm ramp with monotonically falling
  luminance. This keeps "good" and "bad" readings independent of the
  accent and is colour-vision-deficiency safe by construction: there is no
  red/green opposition anywhere in the product.

## Token architecture (`frontend/src/styles/tokens.css`)

**Dark is the unconditional `:root` default — no `prefers-color-scheme`
fallback for the initial theme.** This is the single biggest structural
change from session 15 (which used `@media (prefers-color-scheme: dark)`
to decide the ACTIVE scheme). Now, the base `:root` block carries the dark
values directly; light ("Parchment") is an opt-in override under
`:root[data-theme="light"]`, applied only by a manual toggle
(`theme/ThemeProvider.tsx`, backed by `localStorage['compass-theme']`) and
duplicated in `index.html`'s inline pre-paint script (both must read the
exact same rule — "only `'light'` opts out of dark" — or a future edit to
one silently desyncs from the other).

Two layers, same reasoning as session 15's file, carried forward because
the underlying Tailwind v4 constraint that motivated it is unchanged:

1. **Private `--cp-*` variables** (plain `:root` custom properties, two
   blocks — the base block holding dark values, the
   `:root[data-theme="light"]` block holding light overrides) hold the
   real per-scheme colour VALUES. Plain custom properties are never
   tree-shaken by Tailwind's `@theme` compiler — the exact bug this
   project already hit once (session 15's own subsystem palette). Every
   colour any JavaScript module reads via `getComputedStyle`
   (`lib/chartTheme.ts`) reads one of these `--cp-*` names, or a
   `--subsystem-N`/`--scale-N` value declared the same way, never an
   `@theme`-only token.
2. **The `@theme` block maps every public Tailwind-facing name**
   (`--color-bg`, `--color-accent`, `--color-scale-0..5`, ...) to
   `var(--cp-*)`, so ordinary utility classes (`bg-bg`, `text-accent`)
   resolve through the same switchable value with zero per-component
   `data-theme` branching. Verified directly in the production build
   (`npm run build`'s compiled CSS): `.bg-bg{background-color:var(--color-bg)}`
   and `--color-bg:var(--cp-bg)` — a real `var()` chain, not an inlined
   literal, and the compiled
   `:root[data-theme=light]{...--cp-bg:#f6f4ec...}` block is present and
   complete.

A plain, UNLAYERED `:root[data-theme="light"]` rule always wins the
cascade over `@theme`'s own compiled output (Tailwind v4 places it inside
`@layer theme`, and unlayered CSS beats layered CSS at equal specificity
regardless of source order — the exact mechanism session 15's own Known
Hazard #1 documented) — this is what makes overriding a token also
consumed by `@theme` actually take effect, with no indirection tricks
beyond the `--cp-*` layer itself.

**`index.css` also gained `@custom-variant dark`**, repointing Tailwind's
`dark:` variant at `[data-theme="dark"]` instead of its v4 default
(`prefers-color-scheme`). `ThemeProvider` always stamps an EXPLICIT
`data-theme="dark"|"light"` (never leaves it absent) specifically so this
selector has something concrete to match at all times. Without this, every
un-rebuilt page's `dark:slate-*` pairs (see the transitional remap below)
would track the OS setting instead of the in-app toggle — contradicting
the "no OS fallback" rule the moment a real `dark:` class is exercised.

### Heat ramp and subsystem palette

**Six-stop heat ramp** (`--color-scale-0..5`) is the one ordered scale for
severity/risk/"how bad" — never green (rule R2), and per section 3.1,
"severity maps onto that ramp and nowhere else": `low = scale-1`,
`med = scale-3`, `high = scale-5`.

**Subsystem categorical palette — re-derived from scratch this session.**
Section 3.1's own "starting proposal" hex values (verdigris/clay/slate
blue/ochre/teal/rosewood/olive/apricot/petrol/bronze/sage) **failed
`scripts/verify-subsystem-palette.mjs` outright** — several pairs (clay,
apricot, and the session's own slot-8 guess, all warm oranges clustered
close in hue and lightness) scored as low as ΔE 1.7 under protanopia,
nowhere near the threshold of 8. Re-deriving a second set by eye risked
repeating the exact same mistake, so this session instead searched HSL
space programmatically: greedy farthest-point selection under the SAME
Machado/Oliveira/Fernandes simulation the verification script itself runs,
seeded only with the one fixed value section 3.1 requires (slot 1 = the
accent verdigris, `#5FB99A`), restricted to hues OUTSIDE a generously wide
215°-345° band (well past a literal violet/magenta range alone, so nothing
borderline indigo or orchid could slip through a maximiser that only
optimises pairwise distance, never hue family — rule V1) and to a muted
saturation/lightness gamut (S 26-52%, L 38-64%) so the result still reads
as hand-picked instrument colours rather than an optimiser's neon output.

```
01 #5fb99a verdigris (accent)   05 #9cc379 willow       09 #578bc7 cerulean
02 #bfb740 mustard              06 #a87438 bronze       10 #80424e maroon
03 #913030 brick                07 #7291ac dusty blue   11 #c2cf6e chartreuse
04 #425f80 slate blue           08 #c75766 rosewood *   12 #a1935e khaki
```
\* this session's deliberate choice for the one slot section 3.1 left
unfilled — a warm rose, clearly outside the violet band.

```bash
cd frontend
node scripts/verify-subsystem-palette.mjs
```

```
normal        worst pair: [1]#bfb740 vs [10]#c2cf6e  deltaE=16.2
protanopia    worst pair: [5]#a87438 vs [11]#a1935e  deltaE=13.0
deuteranopia  worst pair: [4]#9cc379 vs [11]#a1935e  deltaE=12.4
tritanopia    worst pair: [1]#bfb740 vs [11]#a1935e  deltaE=12.5

Worst deltaE across all 4 vision types: 12.4 (threshold 8)
```

Comfortably above threshold — the closest pair (mustard vs. khaki, under
deuteranopia simulation) is still 55% past the minimum. Scheme-invariant by
design (declared once, no `:root[data-theme="light"]` override) — a
subsystem's colour identity must not change between a light-mode and
dark-mode screenshot of the same repo.

## Typography

Three self-hosted Fontsource variable families, imported once in
`main.tsx`, no runtime Google Fonts request:

| Token | Family | Role |
|---|---|---|
| `--font-display` | Newsreader (+ italic axis) | Wordmark, hero, section headings, metric names in explainers |
| `--font-sans` | Inter | Body copy, UI labels, buttons, nav |
| `--font-mono` | JetBrains Mono | Shas, paths, run ids, every numeral in a table or metric row |

`font-variant-numeric: tabular-nums` is set globally on `html` (inherited
everywhere) plus again on `.cp-stat` (the mono numeric-readout utility
class). `lucide-react` is the only icon source anywhere in the app from
this session onward (rule V2) — no other icon set may be added.

## `lib/chartTheme.ts` — the single source for every renderer

Unchanged in shape from session 15: the one module `recharts`,
`react-force-graph-2d`, `d3-hierarchy` treemaps, and `three.js` all read
colour through, via `getComputedStyle` at module load with a hardcoded
dark-mode fallback for each value (dark is now the default scheme, so the
fallback tracks it — this is also what makes the module work under
Vitest's jsdom, which never loads `tokens.css`). Repointed at the new
`--cp-*`/`--scale-*`/`--subsystem-*` names this session; every exported
name (`SUBSYSTEM_PALETTE`, `RISK_SCALE`, `SEVERITY_COLOR`, `CHROME`,
`rechartsTheme`, `riskScaleColor`, ...) is unchanged, only the values
underneath. `RISK_SCALE` is now a 6-entry array (was 5).

## Primitives (`frontend/src/components/ui/`)

Rebuilt against the new tokens, same export names/prop shapes as before
(no API churn for sessions 2-4 to fight): `Button`, `Input`, `Select`
(Radix), `Tabs` (Radix), `Tooltip` (Radix), `Drawer` (Radix `Dialog`),
`Badge`, `Chip`, `Table`, `Skeleton`, `Toast` (Radix). New this session:
`Alert` (5 variants, one lucide icon + body slot), `Card` (eyebrow + serif
heading convention — see CLAUDE.md's Frontend section for why the OLD
top-level `components/Card.tsx` is deliberately left in place, untouched,
alongside this one), `SegmentedControl` (Radix `Tabs`-based same-page view
switcher), `InfoTooltip` (the mechanism session 2's explainer copy reaches
the screen through).

Motion primitives (`frontend/src/components/motion/`, all new): `Reveal`
(one-shot fade-up), `CountUp` (hand-written spring counter), `WordReveal`
(word-by-word serif reveal — deliberately not a letter-blur variant),
`Expander` (pure-CSS `grid-template-rows: 0fr→1fr` disclosure). Every one
independently checks `usePrefersReducedMotion()` — the global CSS
`prefers-reduced-motion` override in `index.css` cannot reach a
JS-driven `motion` animation or spring.

## Accessibility — measured, not eyeballed

### Contrast

Every semantic text/background pairing was checked against the real WCAG
2.x relative-luminance formula (a hand-written script, not a linter's
approximation), for both schemes. **This process caught two real,
concrete failures baked into the locked section-3.1 hex values
themselves** — recorded in full under "Known Hazards" below, since they
are exactly the kind of bug this measurement discipline exists to catch
before it ships, not after.

| Pair | Dark | Light |
|---|---|---|
| text on bg | 11.27:1 | 10.06:1 |
| text on bg-elevated | 10.56:1 | 10.89:1 |
| text-muted on bg | 5.90:1 | 5.20:1 |
| text-muted on bg-elevated | 5.53:1 | 5.62:1 |
| text-heading on bg | 17.03:1 | 16.45:1 |
| text-heading on bg-elevated | 15.95:1 | 17.80:1 |
| accent on bg (link text) | 8.30:1 | 5.93:1 |
| accent on bg-elevated (link text) | 7.78:1 | 6.42:1 |
| accent-contrast on accent (primary button) | 8.08:1 | 6.42:1 |
| success on bg-elevated | 7.45:1 | 5.59:1 |
| warning on bg-elevated | 7.78:1 | 5.59:1 |
| danger on bg-elevated | 5.44:1 | 6.07:1 |
| info on bg-elevated | 7.08:1 | 6.72:1 |
| **SeverityChip low** (scale-ink-dark on scale-1 fill) | 9.68:1 | 5.28:1 |
| **SeverityChip med** (scheme-conditional ink on scale-3 fill) | 5.53:1 | 4.88:1 |
| **SeverityChip high** (scale-ink-light on scale-5 fill) | 6.19:1 | 9.09:1 |
| border-interactive on bg-elevated (non-text, 3:1 bar) | 5.53:1 | 5.62:1 |
| **scene-overlay-text on scene-overlay-bg** (3D city HTML labels, session 4) | 15.95:1 | n/a — scheme-invariant |
| **scene-overlay-text-muted on scene-overlay-bg** (session 4) | 5.53:1 | n/a — scheme-invariant |
| diverging-worsen as text (compare deltas, session 4 new usage of the existing `--scale-3` value) | 5.61:1 | 5.01:1 |
| diverging-improve as text (existing `--cp-accent` value — identical to "accent on bg-elevated" above) | 7.78:1 | 6.42:1 |
| **RiskRow low-confidence indicator, border-only** (`border-l-2 border-l-warning`, non-text, 3:1 bar; session 4 — see Known Hazard #5) | 7.78:1 | 5.59:1 |
| **ErrorState message, text on danger-bg** (session 4 fix — was `text-muted`, see Known Hazard #5) | 9.84:1 | 9.09:1 |

Every row clears its bar (4.5:1 for normal text, 3:1 for non-text UI
component boundaries) with real margin. `--color-border`/
`--color-border-strong` remain **decorative** dividers (card outlines,
list separators) and are NOT held to the 3:1 non-text bar — WCAG 1.4.11
applies to boundaries that identify an interactive component's state, not
incidental structural lines; measured directly, `border-strong` against
`bg-elevated` is only 1.60:1 (dark) / 1.97:1 (light), which is fine for a
decorative card edge and is exactly why it must never be used for an
Input/Select/Button boundary (see Known Hazard #1 below).

### Known Hazards, as they actually happened this session

1. **Section 3.1's own locked hex values fail real contrast at both ends
   of the heat ramp, used as text/border colour.** `--color-scale-5`
   (dark scheme, `#9e4038`) measured only **2.84:1** against
   `--color-bg-elevated` as text/border — below even the 3:1 non-text bar,
   nowhere near the 4.5:1 body-text bar `SeverityChip`'s own label needs.
   `--color-scale-1` (light scheme, `#9c8a3e`) measured **3.37:1** —
   clears 3:1 but fails 4.5:1. This is not a bug this session introduced by
   choice of USAGE; it's inherent in the heat ramp's own lightness
   ordering (it runs light→dark as severity increases, which reads
   correctly as small text against a LIGHT page background but loses
   contrast at the dark end against a DARK background, and loses it again
   at the light end against a LIGHT background). Fixed by rendering
   `SeverityChip`/`Badge`'s severity tones as a **solid FILL** (background
   = the scale-N stop itself) instead of an outline, with the label set in
   one of two new FIXED (never scheme-switching) ink tokens —
   `--color-scale-ink-dark` (`#14170f`) / `--color-scale-ink-light`
   (`#fbfaf5`) — chosen PER SEVERITY TIER, not derived from a generic
   "is this stop light or dark" rule, because the ramp's middle stop
   (scale-3, "med") needs the OPPOSITE ink in each scheme (dark ink in
   dark scheme, light ink in light scheme — `text-scale-ink-light
   dark:text-scale-ink-dark`, where `dark:` correctly tracks the app's own
   manual toggle via `@custom-variant dark`, not the OS setting). See
   `styles/tokens.css`'s own comment at the `--color-scale-ink-*`
   declaration for the full reasoning, and the contrast table above for
   all six (2 schemes × 3 tiers) measured results.
2. **`--color-border-strong`, ALSO a locked section-3.1 value, fails the
   3:1 non-text bar against `--color-bg-elevated` in both schemes** (1.60:1
   dark, 1.97:1 light) — yet this session's own first pass at `Input`,
   `Select`'s trigger, and `Button`'s secondary variant used it directly
   as their interactive boundary colour, exactly the WCAG 1.4.11 violation
   session 15's own `--color-border-interactive` token existed to prevent.
   Section 3.1 never actually specified a dedicated interactive-boundary
   token, only a decorative one — the same gap session 15 hit for a
   different palette. Fixed by adding `--color-border-interactive` (not in
   section 3.1's list, added per the rebuild spec's own "add a token,
   follow the naming conventions" rule), reusing `--cp-text-muted`'s
   already-measured-safe value (5.53:1/5.62:1 against `bg-elevated`) rather
   than inventing a fourth colour — every primitive with a real interactive
   boundary now uses this token, `--color-border-strong` reverts to purely
   decorative use.
3. **`--leading-*`/`--tracking-*` had to move INTO `@theme`, not stay plain
   `:root` properties like `--space-*`/`--dur-*`.** Tailwind v4 recognises
   `--leading-*` and `--tracking-*` as real theme namespaces that generate
   (and, if redefined, override) the `leading-*`/`tracking-*` utility
   classes themselves — found directly this session when several already-
   written call sites (`tracking-tight` on the landing wordmark,
   `leading-snug` on `Card`'s title, plus a handful of pre-existing
   un-rebuilt-page usages of `tracking-wide`) turned out to be silently
   resolving to Tailwind's OWN stock values (`0.025em`, `1.375`) instead
   of this file's spec'd `0.09em`/`1.35`, because the tokens were declared
   as plain, non-`@theme` properties — inert as far as those utility
   classes were concerned. `--space-*`/`--dur-*` are NOT Tailwind
   namespaces in the same way and correctly stay outside `@theme` (see
   their own comment in `tokens.css`). Also caught twice this session,
   the same way: a literal `*/` substring formed by two adjacent tokens
   in a comment (`--leading-*/--tracking-*`, and separately
   `gap-*/px-*/py-*`) silently closing the CSS comment early and turning
   the rest of the sentence into invalid CSS — `npm run build` fails
   loudly on this (a real CssSyntaxError), which is what caught both
   instances; grep for `[a-zA-Z0-9_-]\*/[a-zA-Z0-9_-]` before adding a
   comment listing several `--foo-*`-shaped token names back to back.
4. **Both hazards above were caught by writing the actual pairings out and
   measuring them, not by re-reading section 3.1's prose.** A "the locked
   palette is accessible" claim is only as good as checking it against how
   the palette is ACTUALLY consumed by a real component — the rebuild
   spec's own decision #5 ("not negotiable, not adjustable to taste")
   describes the palette VALUES, not the components built on top of them;
   both fixes here changed component-level USAGE (fill vs. outline, which
   named token a boundary reads from) while leaving every one of section
   3.1's given hex values completely untouched, which is the version of
   "follow reality when spec and reality disagree" this session actually
   applied — see `DESIGN_NOTES.md`'s entry for this session for the
   judgement call recorded in full.

### Focus, keyboard, motion

- `:focus-visible` gets a 2px solid `--color-focus` outline with a 2px
  offset, globally, in `index.css`.
- Every primitive with real interaction semantics (`Tabs`, `Tooltip`,
  `Select`, `Drawer`, `Toast`, `SegmentedControl`) is a Radix primitive
  underneath — keyboard behaviour, ARIA roles, and focus management are
  not hand-rolled.
- `@media (prefers-reduced-motion: reduce)` is a single global CSS rule in
  `index.css`; every JS-driven motion primitive additionally and
  independently checks `usePrefersReducedMotion()` (rule M5), verified
  manually this session via a Playwright context with `reducedMotion:
  "reduce"` set.

## Transitional compatibility remap — DELETE IN SESSION 4

Sessions 3/4 have not rebuilt their pages yet, and every currently
un-rebuilt page/component (everything under `pages/onboard/`,
`pages/audit/`, `DashboardPage`, `PortfolioPage`, `ComparePage`, plus
`NarrativeBlock`, `FindingItem`, `EvidencePanel`, `GraphCanvas`,
`ModeSelect`, `DirectoryTreemap`, `CodeCity` — shared components this
session deliberately left untouched) still references BOTH raw Tailwind
`slate-*`/`indigo-*` utilities with explicit `dark:` pairs AND the
session-15 SEMANTIC token names (`bg-surface`, `text-ink`, `text-ink-muted`,
`border-signal`, `text-sev-high`, `text-conf-high`, `bg-risk-2`, ...) —
every shared primitive this repo had before session 15 was refit onto the
latter, and that refit was never undone, so it's actually the LARGER
surface of the two, not the raw Tailwind palette. The rebuild spec's own
Part B instruction only named the raw-palette remap explicitly; leaving
the semantic-name remap out would have broken literally every un-rebuilt
page and every shared component this session did not touch — "the app
stays fully functional and reviewable" is not achievable without it. See
`DESIGN_NOTES.md` for this session's own note recording this as a
deliberate reading of the spec, not an oversight.

**Both are remapped in `tokens.css`, inside a clearly fenced
"TRANSITIONAL" comment block** — `slate-50..950` and `indigo-50..950` onto
new warm-neutral/verdigris-family ramps; `--color-signal`, `--color-ink`/
`-muted`/`-faint`, `--color-surface`/`-2`/`-inset`, `--color-sev-*`,
`--color-conf-*`, `--color-risk-0..4`, `--color-recency-*` onto the
equivalent new-system value each old name's ROLE maps to (documented
token-by-token at each declaration in `tokens.css` itself).
**`--color-border-interactive` is the one name declared only ONCE**, not
duplicated between the new and transitional sections — old and new code
want the identical value for the identical purpose, so un-rebuilt pages
using it get the Known-Hazard-#2 accessibility fix for free.

**Session 4 deletes this entire fenced region** once no page references
any name inside it — grep for the fence comment in `tokens.css` before
touching a page that still needs it, and re-run
`npm run typecheck`/`npm run build` after deleting it to confirm nothing
still resolves through a name that's gone.

## What this session deliberately did not do

See `DESIGN_NOTES.md` for the full, dated entry: judgement calls made (the
semantic-name remap scope, the `/repos/:id/risk` route coincidence, the
`chartTheme.test.ts` anchor rewrite), and structural observations noticed
but out of scope for a foundation session (the mobile header nav's tight
wrapping at 360px, `EvidencePanel`/`FindingItem`/`NarrativeBlock` left on
the old violet-accented styling pending session 2's explicit re-theme onto
`--color-info`).

## UI rebuild session 2 update — `NarrativeBlock` re-themed onto `--color-info`

`NarrativeBlock.tsx`'s generated-content box now uses `border-info`/
`bg-info-bg`/`text-info` (already-measured tokens — see the contrast table
above, "info on bg-elevated": 7.08:1 dark / 6.72:1 light; `--color-info-bg`
is a low-opacity tint composited over that same surface, so its effective
contrast is bounded by the same measurement, not a new pairing needing its
own row) in place of the outgoing hardcoded `violet-*` Tailwind utilities
with manual `dark:` variants. No new token was added — this session
consumed an existing one. `NarrativeBlock.test.tsx` now asserts the
rendered markup contains `bg-info-bg` and never the string `"violet"`.
Nothing else about the component changed (still exactly three surfaces,
still renders `null` with the toggle off or while loading, per rule
V1/CLAUDE.md's own narrative-layer rules).

## UI rebuild session 4 update — the final accessibility/contrast/motion/viewport sweep

Session 4's Part H is the first time this rebuild ran `@axe-core/playwright`
across the WHOLE app (every route, both colour schemes) against real,
un-mocked data (a live pinned showcase repository, `spring-projects/
spring-petclinic`, through the project's own configured Neon
`DATABASE_URL`, read-only). Installed with `--no-save` per the session's
own instruction — it is not a `package.json` dependency and is not wired
into CI. Two full passes: **22 violations found** on the first sweep
(26 route×scheme combinations), **0 remaining** on the final sweep after
fixes below. Every fix here changed component/page code, never a section
3.1 locked hex value.

### New tokens this session

`--color-scene-overlay-bg`/`-border`/`-text`/`-text-muted` (Part F) —
the 3D city's floating HTML labels (`components/CodeCity.tsx`, drei's
`<Html>` overlays projected over the WebGL canvas) needed a fixed, always-
dark chip treatment regardless of the app's light/dark toggle, matching how
the city's own lighting/ground already don't reskin with the toggle (rule
V3's own carve-out) — the same convention on-canvas map labels use
everywhere. Declared once, scheme-INVARIANT (no light override, same
treatment as `--color-subsystem-*`), replacing what used to be raw
`slate-900`/`slate-700`/`slate-300` Tailwind utility classes (the one
remaining `slate-`/`indigo-` usage this session's Part F grep found outside
the pages it was already deleting).

### Known Hazards, as they actually happened this session

1. **A tab nav that measures as correctly self-contained by every DOM
   property (`clientWidth`, `scrollWidth`, `getBoundingClientRect()`) can
   still inflate `document.documentElement.scrollWidth` on a sufficiently
   TALL page.** Found on `/repos/:id/findings` specifically — the only one
   of the eight repo surfaces tall enough, against real data, to trigger a
   document-level vertical scroll. `RepoLayout`'s tab `<nav>`
   (`overflow-x-auto`, `flex`) measured `clientWidth=328`/`scrollWidth=559`
   (correctly self-clipped) and its own `getBoundingClientRect().right`
   never exceeded the viewport, yet `document.documentElement.scrollWidth`
   still read 578 against a 360px viewport — repeatable, not a timing
   fluke, confirmed across three fresh browser contexts with a 3.5s settle
   time. A page-level `overflow-x: hidden` on `html, body` (`index.css`) is
   the fix: an absolute backstop against this class of nested-scroll-
   container edge case, independent of whatever Chromium's exact
   `scrollWidth` computation is doing internally. Verified after the fix:
   all 13 routes (8 repo surfaces + 5 global pages) read exactly `360` at a
   360px viewport, in a fresh context, every time.
2. **Two separate, genuine 360px overflow bugs were hiding UNDER the nav
   issue above and only became visible once it was fixed** — both real
   layout defects, not nav-related: (a) `RepoLayout`'s repository URL link
   (`{repo.url}`, e.g. `https://github.com/spring-projects/spring-
   petclinic`) had no `break-all`/`truncate` class, so one long unbroken
   string forced its containing flex row wider than the viewport; (b)
   `OverviewPage`'s "Three things to know" row and its entry-points list
   had the same shape of bug twice — a flex item with no `min-w-0` next to
   a `shrink-0` sibling, so a long unbroken token inside it (a Java package
   path in an `ORPHANED_HOTSPOT` message; the `graph_inferred` entry-point
   kind's full-sentence label wrapped in a `shrink-0` badge pill meant for
   short text) pushed the row wider instead of wrapping. Fixed with
   `break-all`/`break-words`/`min-w-0` at each site and `flex-wrap` on the
   entry-point badge row — never by touching the palette or the type scale.
3. **`Expander`'s pure-CSS collapse (the `grid-template-rows: 0fr → 1fr`
   technique, rule M4) keeps its children permanently in the DOM — a
   collapsed panel is visually and (via `aria-hidden`) semantically hidden,
   but was never actually removed from the tab order.** `aria-hidden-focus`
   (axe-core, serious): a collapsed `ScoreExplainer`'s `InfoTooltip` buttons
   were still real, focusable elements a keyboard user could tab into while
   invisible. `aria-hidden="true"` alone only ever hides content from
   assistive tech; it says nothing about focusability, which is exactly the
   gap this rule exists to catch. Fixed with React 19's `inert` prop on the
   same collapsed panel, applied alongside (not instead of) `aria-hidden` —
   `inert` is the one primitive that makes a subtree simultaneously
   non-focusable AND assistive-tech-hidden, atomically, which is what
   "collapsed" was always supposed to mean here.
4. **`SegmentedControl` (session 1, used by every merged surface's
   `?view=`/`?tab=` switch) never rendered a Radix `Tabs.Content` panel at
   all — but Radix's `Tabs.Trigger` sets `aria-controls` unconditionally,
   pointing at an id that consequently never existed anywhere in the DOM.**
   `aria-valid-attr-value` (axe-core, critical) on every one of its four
   real call sites (Map, Risk, Structure, Evolution). This is a broken
   IDREF, not a missing-attribute problem — the fix is a real (if empty)
   `Tabs.Content` per option, which Radix only mounts for the currently
   active one, giving that trigger's `aria-controls` a genuine target at
   all times.
5. **A background TINT used to mark a "distinct row treatment" can fail
   contrast for text sitting on top of it, even when the same text passes
   comfortably against the page's normal background.** `RiskRow`'s
   low-confidence highlight (`bg-warning-bg` across the whole row) measured
   `text-muted` at 4.4:1 against the composited tint in the dark scheme —
   under the 4.5:1 body-text bar — across ~126 real elements on a
   real-sized risk list (`color-contrast`, axe-core, serious). Separately,
   `ErrorState`'s message paragraph (`text-muted` on `bg-danger-bg`)
   measured 4.36:1 in the light scheme. Both fixed the same way: stop using
   a translucent colour FILL as the signal for muted text sitting on top of
   it, and use either a plain left BORDER (RiskRow — matching the "border
   carries the signal, fill stays neutral" convention `HeuristicNote`/
   `PartialResultNotice` already established, at 7.78:1/5.59:1 as a 3:1
   non-text boundary) or the full-strength `text` token instead of
   `text-muted` (ErrorState, now 9.84:1/9.09:1). Neither fix touched a
   locked palette value — both changed which existing token a component
   reads, and in RiskRow's case, which VISUAL LANGUAGE (fill vs. border) it
   uses at all.
6. **A scrollable list of plain (non-interactive) rows is invisible to
   keyboard navigation unless the scroll container itself is
   focusable.** `scrollable-region-focusable` (axe-core, serious) on the
   Structure surface's four `overflow-y-auto` lists (unreferenced files,
   ranked coupling pairs, structural/historical blast-radius results) —
   each row is plain text with nothing else to tab to, so without
   `tabIndex={0}` (+ an `aria-label` naming what's scrolling) on the `<ul>`
   itself, a keyboard-only user had no way to reach or scroll these lists
   at all. Three OTHER `overflow-y-auto` regions in the app
   (`FilePicker`'s suggestion dropdown, `HomePage`'s GitHub-repo picker,
   `GlossaryDialog`'s term list) were reviewed and left alone — each
   contains real `<button>`/interactive children per row already in the
   tab order, which is what keeps axe's rule from firing on them; this is
   a property of the rule (an empty-of-focusable-descendants scroll
   container specifically), not a coincidence.
7. **A heading level can be skipped even on a page an earlier session
   built and manually reviewed, if the reviewer only inspected geometry
   and colour, not the accessibility tree.** `heading-order` (axe-core,
   moderate) on `/how-it-works`: the page's own `h1` was followed directly
   by each pipeline stage's own `h3` (`OverviewPage`'s only h2-level
   section titles come AFTER the stage list, not before), skipping h2
   entirely. Fixed by promoting the per-stage heading to `h2` — a one-line
   change, worth recording because it shows the sweep catching something
   genuinely outside this session's own new code, exactly as Part H's
   "final quality pass across the whole app" instruction intends.
8. **`page-has-heading-one` (axe-core, moderate) fired on `/dashboard` and
   `/portfolio` for an anonymous visitor specifically** — both pages'
   `<h1>` only ever rendered on the SUCCESS path; the loading/logged-out/
   error early returns bypassed it entirely, which is a real, common state
   for these two pages (an anonymous visitor hits both routinely). Fixed by
   keeping the `<h1>` present in every branch of both components' return
   value, rather than only the happy path.

### Contrast, reduced motion, 360px, CSP — final state

- **Contrast**: table above updated with every new/changed pairing this
  session introduced; every row clears its bar. See the fixes in Known
  Hazard #5 above for the two that initially failed.
- **Reduced motion**: `prefers-reduced-motion: reduce` context across all
  13 routes — zero console/page errors, consistent with sessions 1-3's own
  verification of the CSS-level and JS-level (`usePrefersReducedMotion`)
  halves of rule M5, neither of which this session touched.
- **360px**: all 13 routes (8 repo surfaces + landing, how-it-works,
  methods, dashboard, portfolio) measured `document.documentElement.
  scrollWidth === 360` in a fresh browser context, both colour schemes,
  after the fixes above. `/shared/:slug` was not included in the live
  sweep (creating a real share link needs an authenticated owner, which
  this read-only verification pass didn't have) — its own component was
  read and reviewed directly instead: it renders only `LoadingState`/
  `ErrorState` (both already covered elsewhere in this same sweep) before
  redirecting, so there is no route-specific layout of its own to miss.
- **CSP**: see the README/CLAUDE.md Observability and Deployment sections
  for the production-build verification method this session re-ran
  unchanged from session 16's own pass (`frontend/vercel.json` was not
  modified this session).
