# Design notes — structural observations, not fixed this session

Session 15's mandate was a **refit**: apply the new design system, correct
typography/spacing, verify accessibility — never change information
architecture, routes, or what data a page shows (Known Hazard #1 in the
session prompt: "you will be tempted to restructure; don't"). Everything
below is something noticed while touching a page's markup that would
improve the product, but that touching would have mixed a structural
change into a purely visual session, making it impossible to tell which
change broke something if anything did. Logged here instead, per the
prompt's own instruction, for a future session to pick up deliberately.

## Coverage honesty — which pages got which treatment

Given the size of this session (19 routes, ~8,600 lines of existing page/
component code), effort was allocated in three tiers rather than spread
evenly, and that allocation is worth stating plainly rather than letting
"every page was refit" imply a uniform depth it didn't get:

- **Full hand-crafted refit** (new hierarchy, primitive adoption, spacing
  pass, `chartTheme` wiring where charts exist): `HomePage`, `AppShell`,
  `RepoLayout`, `PassportPage`, `TourPage`, `FindingsPage` +
  `FindingItem`/`EvidencePanel`, `RiskPage`, `HealthPage`.
- **`chartTheme`/hex-literal wiring plus targeted token fixes**, but not a
  full line-by-line hierarchy pass: `ArchitecturePage`, `CouplingPage`,
  `HygienePage`, `EvolutionPage`, `PortfolioPage`, `CodeCity`, `MapPage`.
  These pages' recharts/canvas/WebGL colour output was hardcoded hex
  before this session (invisible to the token remap, which only reaches
  Tailwind class-driven chrome) — that was the accessibility- and
  coherence-critical gap, and it's closed. Their surrounding JSX chrome
  was largely left to inherit the palette/radius/shadow remap rather than
  being hand-edited line by line.
- **Token-remap inheritance only** (no direct edits beyond what a global
  mechanical pass touched): `PeoplePage`, `GlossaryPage`, `ImpactPage`,
  `SecurityPage`, `BenchmarkPage`, `CityPage`, `DashboardPage`,
  `ComparePage`. These render coherently — verified by screenshot and by
  the zero-violation axe scan covering several of them directly — because
  they're built almost entirely from the shared components
  (`Card`/`EmptyState`/`SeverityChip`/`ConfidenceMeter`/`StageGate`/etc.)
  that *did* get a full refit, plus the slate/indigo/radius/shadow
  remap. They were not individually redesigned.

None of this is a claim that these three tiers look inconsistent — the
whole point of the token-remap leverage strategy (see DESIGN.md) is that
tier three genuinely does inherit the same visual language as tier one.
It's a claim about where *original design judgement* (not just inherited
tokens) was actually applied, which is the more honest way to describe
"refit every page" than letting the phrase imply nineteen bespoke passes.

## Structural observations (not acted on)

1. **`FindingsPage`'s category/severity filters are two native `<select>`
   elements sitting in a `Card`'s `action` slot** — functionally fine
   (now properly labelled, see DESIGN.md's accessibility section), but the
   session's own `Select` primitive (Radix-based, styled to match the rest
   of the instrument chrome) was built specifically for this kind of
   control and isn't used here. Swapping would be a pure visual
   improvement with no IA change, and would have been in scope, but ran
   into the same time-budget tier-three tradeoff above — noted for a
   quick follow-up rather than done ad hoc under time pressure this
   session.

2. **`ModeSelect` (native `<select>`) and `components/ui/Select.tsx`
   (Radix) now coexist as two different "pick one of these options"
   patterns** for what is, in a few places, a similar interaction (the
   codebase map's colour/edge-mode switches use `ModeSelect`; nothing yet
   uses the new `Select` primitive). This is a deliberate, documented
   split (`ModeSelect`'s own docstring: a plain native select is fine when
   there's no custom popover styling need), not an oversight — but a
   future session doing another primitives pass might reasonably ask
   whether `ModeSelect` should be retired in favour of `Select` everywhere
   for one fewer pattern to maintain.

3. **`HygienePage`'s "commit volume over time" backdrop is still a real
   event timeline, not a volume curve** (CLAUDE.md already documents why:
   no endpoint returns per-day/per-week commit counts). Unrelated to this
   session, but flagged again here because the surrounding chart's new
   visual treatment might make a viewer expect a denser line where there
   genuinely isn't backing data — a future data-layer session, not a
   visual one, is what would resolve this.

4. **The findings category chip (`FindingItem`) and `SubsystemBadge` now
   render visually similar hairline-bordered pills** with different
   colour semantics (category chip: neutral border; subsystem badge: a
   coloured dot). This is intentional — the pill *shape* is shared
   (Badge's own visual language), the meaning is carried by colour/dot,
   not shape — but it's worth a second look from a future session with
   fresh eyes on whether the two are distinguishable enough at a glance in
   a dense findings list where both can appear on the same row.

5. **`tsconfig.app.json` now includes `"node"` in its `types` array**
   (previously `["vite/client", "vitest/globals"]`), needed so
   `src/lib/chartTheme.test.ts` can `import { readFileSync } from
   "node:fs"` to read `styles/tokens.css` and four page/component source
   files directly off disk for the Part F anti-drift and token-completeness
   tests (Vite's `?raw` import suffix was tried first and rejected — it
   silently returns an empty string for `tokens.css` specifically, because
   `@tailwindcss/vite` transforms every `.css` file reachable from the
   Tailwind import graph regardless of a `?raw` query; see DESIGN.md's
   Known Hazards). This is a small, permanent widening of what type
   information is available to the whole `src` tree (in principle a
   browser-only file could now reference `process`/`Buffer` without a type
   error, though nothing does) — flagged here rather than silently
   accepted, since it's exactly the kind of scope-widening a future
   session should notice happened and decide whether it's still the right
   call, not rediscover by accident.

6. **`StageGate` gained an optional `skeleton` prop so a page can supply a
   loading placeholder shaped like its own eventual content, but no page
   actually passes one yet** — every `StageGate` call site in the app
   still falls back to the generic `LoadingState` (three shaped bars, a
   reasonable but generic stand-in). The mechanism exists and is exercised
   by nothing; the honest claim is "loading no longer looks like a
   spinner that could belong to any page" (a real improvement over the
   pre-session state), not "every skeleton matches its final layout
   exactly." A follow-up session wiring a couple of `skeleton` props for
   the heaviest pages (`RiskPage`'s ranked list, `MapPage`'s graph) would
   close this gap cheaply, now that the prop exists.

## Not a structural note, but worth surfacing

`npm audit` reports 3 high-severity advisories after this session's
`npm install radix-ui` (and the temporary, `--no-save` `@axe-core/playwright`
install, which never touched `package.json`/`package-lock.json`). Not
investigated or fixed this session — outside a visual-identity session's
scope, and `plan/RULES.md` sec 1.3 already requires asking before adding a
dependency, which was done for `radix-ui` per the session prompt's own
explicit permission; a transitive advisory in that dependency's own tree is
a separate decision for whoever reviews `npm audit`'s actual output next.
