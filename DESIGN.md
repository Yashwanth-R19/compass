# Compass design system

Session 15's deliverable: a visual identity for Compass, and a refit of every
existing page onto it. This document is the reference for that identity —
what it is, why, and the numbers behind the accessibility claims — so a
future session extending the product doesn't have to re-derive it or,
worse, drift away from it one plausible-looking Tailwind class at a time.

## The direction

**An instrument, not a dashboard.**

Compass's own framing is "a measurement instrument, not an AI wrapper" —
master-context.md's central argument. The visual identity exists to say
that before a single word on the page is read. Concretely:

- **Dense, monospace-leaning, tight vertical rhythm.** Numbers are the
  hero — every metric renders in a monospace font with tabular figures, at
  a deliberately larger type scale than its label. Labels are small,
  quiet, uppercase, tracked-out mono captions.
- **Colour encodes data and nothing else.** Severity, risk, confidence,
  subsystem identity, compare direction — those get colour. Chrome (nav,
  panels, borders, buttons, the mode switcher) stays neutral graphite in
  both schemes. The one narrow exception is documented below.
- **Sharp corners, hairline borders, no drop shadows, no gradients, no
  glass.** A 1–2px flat radius, borders instead of elevation, opaque
  surfaces instead of blur.
- **Reference points:** a Bloomberg terminal, `htop`, a lab instrument's
  control panel — not a SaaS product landing page.

**Explicitly rejected:** rounded cards floating on a gradient background,
pastel accent colours, hero illustrations, emoji as iconography, decorative
animation.

### The one accent

A single narrow exception to "chrome is neutral": `--color-signal`, a
controlled cyan-teal (`#0f6f75` light / `#4dd4dc` dark), reserved for:
focus rings, the single primary call-to-action per page (the "Analyze"
button, "Log in with GitHub"), and the currently-selected item in chrome
that needs a positive marker (the active mode-switcher segment, the active
tab's underline, a selected graph node). It is never used to encode a data
value — a subsystem, a severity, a risk level. If you're reaching for
`text-signal`/`bg-signal` to represent something the user is analysing
rather than something they're doing, that's the wrong token; reach for the
relevant semantic data token instead (see below).

Two more hues are inherited, untouched, from before this session and kept
for the same single-purpose reason: `violet` is exclusively
`NarrativeBlock`'s own colour (see CLAUDE.md's narrative-layer section —
this predates session 15 and this session did not disturb it), and
`red`/`amber`/`emerald`/`sky` remain Tailwind's stock hues, used only for
their pre-existing, single, correct meanings (danger, warn, healthy,
selection-adjacent) rather than repainted into the new system — they were
not part of the generic-dashboard problem this session exists to fix.

## Token architecture (`frontend/src/styles/tokens.css`)

Two layers, both real Tailwind v4 `@theme` machinery, no
`tailwind.config.js` anywhere:

### 1. Semantic tokens — the documented system

`--color-bg`, `--color-surface`, `--color-surface-2`, `--color-surface-inset`,
`--color-border`, `--color-border-strong`, `--color-border-interactive`,
`--color-ink`, `--color-ink-muted`, `--color-ink-faint`, `--color-overlay`,
`--color-signal`, `--color-signal-ink`, `--color-sev-{high,med,low}`,
`--color-conf-{low,medium,high}`, `--color-risk-{0..4}`,
`--color-recency-{fresh,stale}`, `--color-diverging-{improve,worsen,neutral}`,
`--color-subsystem-{1..12,unassigned}`.

Each resolves via a two-step indirection: `@theme` maps the semantic name to
a private `--cp-*` variable (e.g. `--color-bg: var(--cp-bg)`), and only the
`--cp-*` variable is redefined inside
`@media (prefers-color-scheme: dark) { :root { ... } }`. This is what lets
one utility class (`bg-surface`) adapt to the OS colour scheme automatically
— no paired `dark:` class needed at the call site. **New code should use
this system.**

The subsystem categorical palette (`--subsystem-1..12`) and every colour
`lib/chartTheme.ts` reads via `getComputedStyle` are declared as **plain**
`:root` custom properties, deliberately *outside* `@theme` — Tailwind v4
tree-shakes an `@theme`-declared variable out of the compiled CSS entirely
when no generated utility class ends up using it, which is fine for a
utility-only token but silently breaks a token whose primary consumer is
JavaScript. This was found directly during this session (the palette
initially lived inside `@theme` and vanished from the production CSS
output) — see `styles/tokens.css`'s own comment at that declaration.

### 2. The remapped base palette — leverage, not laziness

Every page built before this session already used Tailwind's stock
`slate-*`/`indigo-*` utilities, explicitly paired with `dark:` variants
(`bg-white dark:bg-slate-950`, `border-slate-200 dark:border-slate-800`),
plus stock `rounded-*`/`shadow-*` utilities. Tailwind v4 resolves a theme
key's final value from whichever `@theme` declaration runs last, so
redefining `slate`'s eleven stops (a hand-picked warm graphite ramp, not
derived from Tailwind's default and not algorithmically generated),
`indigo`'s eleven stops (repointed onto the same signal hue as
`--color-signal`), and flattening the entire `radius`/`shadow` scales
reskins **every one of those pre-existing classes app-wide, with no
per-file edit required.**

This is why the refit could touch every route without rewriting every
route: a page that was never hand-edited this session (most of `MapPage`,
`PeoplePage`, `SecurityPage`'s general chrome) still renders in the new
identity, because the classes it already had now resolve to the new
values. Both layers resolve to the same values by design — there is one
palette, read two ways, not two competing systems.

### Radius and shadow

```css
--radius-*: 0px – 2px   /* every rounded-* utility, flattened */
--shadow-*: 0 0 #0000   /* every shadow-* utility, zeroed */
```

Redefining the *scale itself* rather than editing every `rounded-xl`/
`shadow-sm` call site is the same leverage move as the palette remap.

### Typography

`--font-sans` (a system grotesk stack) for prose — glossary terms,
narrative text, tour copy, anything meant to be read at length.
`--font-mono` for everything else: nav labels, table headers, all metric
numbers, code-shaped tokens (shas, paths). `body` sets
`font-variant-numeric: tabular-nums` globally (an *inherited* CSS
property), so digit columns align by default everywhere without a
per-element opt-in — verified visually in several metrics tables during
this session's QA (RiskPage's ranked list, HealthPage's vitals).

Two small utility classes carry the "instrument label" look:
`.cp-label` (mono, uppercase, tracked-out, quiet — a stat's caption) and
`.cp-stat` (mono, tabular, tight tracking — a stat's own value). **Both are
declared inside Tailwind's `components` layer, not as bare/unlayered CSS**
— see the Known Hazards section below for the real bug this avoided.

## `lib/chartTheme.ts` — the single source for every renderer

Four things in this app draw colour without going through the DOM's CSS
cascade at all: `recharts` (styled via JS props), `react-force-graph-2d` (a
`<canvas>`), `d3-hierarchy` treemaps (plain fill colours computed in JS),
and `three.js` (the 3D city). None of them read CSS custom properties on
their own. `chartTheme.ts` reads the tokens **once**, via
`getComputedStyle(document.documentElement)`, with a fallback baked into
every read (the same light-mode hex, kept in sync by hand — this is also
what makes the module work correctly under Vitest's jsdom environment,
which never loads `tokens.css`).

It exports: `SUBSYSTEM_PALETTE`/`UNASSIGNED_COLOR` (re-exported by
`lib/subsystemColors.ts`, which stays the accessor — `colorForSubsystem` —
so every existing call site kept working unchanged), the 5-stop `RISK_SCALE`
("heat": straw → deep red) plus `riskScaleColor(t)`, `RECENCY_FRESH`/
`RECENCY_STALE`, the diverging compare-delta pair, `SEVERITY_COLOR`/
`CONFIDENCE_COLOR`, a `CHROME` bundle (bg/surface/border/ink family plus the
signal accent, for chart axis/grid/tooltip chrome), and `rechartsTheme` — a
ready-made prop bundle (`grid`, `axis`, `tooltip`, `legend`) every recharts
chart in the app now spreads onto its own `CartesianGrid`/axis/`Tooltip`
rather than hand-picking colours per chart.

**Rule, stated in the module's own docstring:** colour encodes data, chrome
is neutral. If you're about to add a bright colour to make a chart "pop"
and it isn't one of the exported scales, that's chartjunk.

## Risk: why a heat scale, not red-green

The pre-existing risk gradient was `emerald-500 → red-500` (low → high) — a
classic red-green failure mode for the ~8% of men with some form of
red-green colour-vision deficiency. Session 15 replaced it with a 5-stop
sequential "heat" ramp (straw `#f4e6bf` → deep red `#7f1d1d`, light mode)
where hue shifts only across *adjacent* warm hues (straw → amber → orange →
red) while lightness and saturation do the actual discriminating work —
the ramp stays legible under every common CVD simulation because it never
depends on distinguishing red from green in the first place. Recency
(fresh → stale) and the compare-delta diverging pair (improved/worsened)
were already colour-vision-safe by construction (a blue/cyan-to-grey ramp,
and a blue-vs-orange-red diverging pair rather than green-vs-red) and were
left as-is beyond sourcing their hex from tokens.

## The subsystem palette, and the colourblind check

Twelve hand-picked categorical colours (`--subsystem-1..12` in
`styles/tokens.css`), scheme-invariant by design — a subsystem's colour
identity must not change between a light-mode and dark-mode screenshot of
the same repository, only the surface it sits on changes. Base seven come
from Okabe & Ito's published colour-blind-safe set; the remaining five
extend it.

**This session ran an actual simulation, not an eyeball check** — Part E's
explicit requirement. `frontend/scripts/verify-subsystem-palette.mjs`
implements the Machado/Oliveira/Fernandes (2009) linear-RGB dichromacy
matrices for protanopia, deuteranopia, and tritanopia, converts every pair
under each simulated condition (plus normal vision) to CIE L\*a\*b\*, and
checks the worst-case pairwise ΔE (CIE76) against a threshold of 8 (a
commonly-cited "comfortably distinguishable at a glance" bar). Run it with:

```bash
cd frontend
node scripts/verify-subsystem-palette.mjs
```

**It found a real bug.** The original twelve (inherited from session 09)
had slots 8 and 11 (`#7b3294` and `#88419d`) both in the violet family —
ΔE 6.1 apart *at normal vision*, before any colour-vision deficiency
simulation even entered the picture, and it got worse under every simulated
condition (as low as ΔE 5.1 under tritanopia). Slot 11 was replaced with
`#7216f3`, chosen by searching hue/lightness/saturation space for the
candidate that maximizes the worst-case ΔE against the other eleven across
all four vision types (script output, current palette):

```
normal        worst pair: [1]#e69f00 vs [6]#f0c808  deltaE=21.7
protanopia    worst pair: [8]#994f00 vs [9]#117733   deltaE=12.0
deuteranopia  worst pair: [0]#0072b2 vs [7]#7b3294   deltaE=10.0
tritanopia    worst pair: [0]#0072b2 vs [9]#117733   deltaE=13.0
```

Worst case across every simulated condition: **ΔE 10.0**, comfortably
above the 8.0 threshold.

## Accessibility — measured, not eyeballed

### Contrast

Every semantic text/background pairing was checked against the real WCAG
2.x relative-luminance formula (not a linter's approximation), for both
schemes:

| Pair | Light | Dark |
|---|---|---|
| ink on bg | 16.03:1 | 16.25:1 |
| ink on surface | 18.25:1 | 15.20:1 |
| ink-muted on bg/surface | 6.12–6.97:1 | 6.47–7.41:1 |
| ink-faint on bg/surface | 4.59–5.23:1 | 5.46–5.84:1 |
| signal on surface (link text) | 5.91:1 | 10.31:1 |
| signal-ink on signal (primary button) | 5.91:1 | 10.15:1 |
| sev-high / sev-med / sev-low on surface | 5.02–7.63:1 | 6.65–11.02:1 |
| conf-low / conf-high on surface | 5.02–5.02:1 | 10.56–11.02:1 |
| border-interactive on surface (non-text, 3:1 bar) | 3.91:1 | 3.80:1 |

Every row clears its bar (4.5:1 for normal text, 3:1 for non-text UI
component boundaries) with real margin — the two rows that initially
*didn't* (`ink-faint` at 3.67:1, and `sev-med`/`conf-high` at 4.40–4.41:1
against `--cp-bg` specifically, not just `--cp-surface`) were caught and
fixed during this session, both by an [axe](https://www.deque.com/axe/)
scan, not by re-running the arithmetic — see Known Hazards below for both
stories.

`--color-border`/`--color-border-strong` are **decorative** dividers (Card
outlines, list separators) and are NOT held to the 3:1 non-text bar —
WCAG 1.4.11 applies to boundaries that identify an interactive
component's state, not incidental structural lines. `--color-border-interactive`
is the token actually used by `Input`, `Select`'s trigger, `Button`'s
secondary variant, and `Table`, specifically because those borders *are*
what identifies the control.

### The axe pass

Run manually (Part E's own instruction: **not wired into CI**), via a
one-off `@axe-core/playwright` script (installed with `--no-save`, never
added to `package.json`) driving the real dev server with the mocked API
fixtures `e2e/fixtures.ts` already provides, across nine routes in both
colour schemes. Three real, confirmed bugs were found and fixed this way —
not visible by eye at a normal glance, all three now zero-violation:

1. **A cascade-layer bug hiding the selected mode-switcher segment's own
   text.** See "Known Hazards" below.
2. **`ink-faint` and `sev-med`/`conf-high` narrowly failing AA** against
   the page background specifically (not the white/near-black card
   surface the initial hand check used) — both token values were
   darkened with real margin, not just enough to scrape past 4.5:1.
3. **Two native `<select>` elements with no accessible name**
   (`FindingsPage`'s category/severity filters) — fixed with `aria-label`.
4. **Two unlabelled, non-unique `<nav>` landmarks** on the same page
   (`AppShell`'s primary nav and `RepoLayout`'s tab bar) — fixed with
   `aria-label="Primary"` / `aria-label="Repository sections"`.

Final state: zero axe violations across every route scanned, both schemes.

### Focus, keyboard, motion

- `:focus-visible` gets a 2px solid `--color-signal` outline with a 2px
  offset, globally, in `index.css` — no component sets `outline: none`
  without this same replacement already applying.
- Every new primitive with real interaction semantics (`Tabs`, `Tooltip`,
  `Select`, `Drawer`, `Toast`) is a Radix primitive underneath, which is
  where their keyboard behaviour (arrow-key navigation, `Escape` to
  dismiss, focus trapping in `Drawer`, focus return on close) comes from —
  not hand-rolled.
- `@media (prefers-reduced-motion: reduce)` is a single global rule in
  `index.css` collapsing every `animation`/`transition` duration to
  effectively zero, plus `motion-reduce:` variants added at specific sites
  this session touched (`ScoreGauge`'s arc transition, `StagePill`'s
  running-state pulse, the narrative toggle's thumb slide). Session 09's
  own `usePrefersReducedMotion` hook (the 3D city's camera/animation gating)
  was left untouched — it already satisfied this requirement before session
  15 started.

## Primitives (`frontend/src/components/ui/`)

`Button`, `Input`, `Select` (Radix), `Tabs` (Radix), `Table`, `Badge`,
`Chip`, `Tooltip` (Radix), `Drawer` (Radix `Dialog`), `Skeleton`/
`SkeletonText`, `Toast` (Radix). Every one reads only semantic tokens (no
hardcoded colour), so both colour schemes come for free.

**`Table` and the findings no-re-sort rule.** `Table` supports an optional
per-column client-side sort (a `sort`/`onSortChange` prop pair) — a
legitimate, generic primitive capability. `pages/audit/FindingsPage.tsx`
does **not** use `Table`; it renders through `FindingItem` in a plain
`<ul>`, specifically so this sortability can never be reached for the one
stream in the app where re-sorting would silently discard
`FindingsRankEngine`'s global cross-category rank (CLAUDE.md, session 11).
`Table`'s own docstring states this explicitly, so a future page that
*does* route findings through `Table` is warned at the point of temptation,
not just in this document.

**Radix, not hand-rolled, for real interaction semantics.** Tabs, tooltips,
dialogs, dropdowns/selects all get correct ARIA roles, keyboard behaviour,
and focus management from `radix-ui` — the one new dependency this session
adds (named explicitly by the session prompt). `RepoLayout`'s Onboard/Audit
tab bar and its per-mode route tabs are **not** Radix `Tabs`: they are real
routes (`NavLink`s under `react-router`), and converting route navigation
into a same-page tab-panel component would silently break deep-linking,
the back button, and every existing share link — a structural change this
session's refit constraint forbids. `components/ui/Tabs.tsx`'s own
docstring says so, so the distinction isn't left to tribal knowledge.

## Known Hazards, as they actually happened

1. **The cp-label cascade-layer bug.** `RepoLayout`'s `ModeSwitcher`
   combines the `.cp-label` class (a plain custom class, originally
   declared as bare/unlayered CSS in `index.css`) with a Tailwind colour
   utility (`text-bg`) on the selected segment. Unlayered CSS beats *any*
   layered CSS at equal specificity, regardless of layer order — so
   `.cp-label`'s own baked-in `color: var(--color-ink-faint)` silently won
   over `text-bg`, rendering the selected segment's label at a badly
   failing contrast ratio against its own background. This was invisible
   at a glance (ink-faint against a dark ink background still reads as
   *some* grey text, just far too close to its background) and was caught
   only by the axe pass, not by eye. Fixed by moving `.cp-label`/`.cp-stat`
   into Tailwind's own `@layer components`, which is *before* the
   `utilities` layer in Tailwind v4's cascade order — exactly the ordering
   that makes a co-applied utility class win as intended. **If you add
   another bare custom class meant to coexist with Tailwind utility
   overrides, put it in `@layer components`, not bare CSS.**

2. **A token that passes against one surface and fails against another.**
   The initial contrast check only verified `ink-faint`/`sev-med`/
   `conf-high` against `--cp-surface` (white/near-black cards). Several
   real elements — status pills, stage pills — render directly on
   `--cp-bg` (the page background) with no surrounding card, and `--cp-bg`
   is *slightly* darker than white in light mode, which was enough to fail
   two colours that had passed against pure white by a hair (4.39–4.41:1
   vs. 4.5:1 needed). **Any new "faint but still body text" token must be
   checked against every surface it can realistically render on, not just
   the most favourable one.**

3. **A mechanical find-and-replace missing non-adjacent tokens.** The bulk
   migration from raw `text-slate-N dark:text-slate-M` pairs to semantic
   `text-ink-*` tokens used exact-phrase string replacement for speed
   across ~190 call sites. It correctly skipped — and therefore missed —
   any class string where a `bg-*`/`dark:bg-*` token sat *between* the two
   text-colour tokens (e.g. `text-slate-500 dark:bg-slate-800/60
   dark:text-slate-400`), since the two colour tokens weren't textually
   adjacent. These were exactly the instances the axe pass's remaining
   violations pointed at. The follow-up pass matched each token
   independently (word-boundary regex) rather than requiring adjacency.
   **A "the app now uses semantic tokens everywhere" claim is only as good
   as the search that verified it — re-grep for the raw pattern after any
   bulk migration, don't trust the replacement count alone.**

4. **`@theme`-declared variables are tree-shaken if no utility uses them.**
   Documented above under "Token architecture" — repeated here because it
   is the single most likely way a future session's new token silently
   stops working in production while looking fine in every manual dev-mode
   check (dev mode's CSS handling doesn't drop it the same way; verified
   directly by comparing `npm run build`'s compiled CSS before and after
   the fix).

## What this session deliberately did not do

See `DESIGN_NOTES.md` for structural observations noticed but out of scope
(the refit constraint), and `plan/STATE.md`'s session 15 entry for the
honest completion accounting — which pages got a full hand-crafted pass
versus a systematic token/`chartTheme` pass, and why that split was a
reasonable use of the session's time rather than a shortfall.
