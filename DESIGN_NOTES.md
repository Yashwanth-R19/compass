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

---

# 2026-09-03 — UI rebuild session 1 (foundation)

Everything above this line is session 15's own entry, describing the
system this session replaced. `plan/UI_REBUILD_SESSIONS.md` sections 1-6
is the normative spec this session implemented; see `DESIGN.md`'s full
rewrite for the new token architecture, contrast table, and palette
verification result. This entry is the judgement-call log the rebuild
spec's own process rules require.

## Judgement calls made, and why

1. **The transitional compatibility remap covers MORE than the spec's own
   Part B literally named.** Part B's instruction ("keep a compatibility
   remap") only names raw Tailwind `slate-*`/`indigo-*` utilities
   explicitly, describing them as what "every existing page" uses. By the
   time this session started, that was only half true: session 15 had
   already refit every shared primitive (`Button`, `Card`, `SeverityChip`,
   `ScoreGauge`, ...) onto its OWN semantic token names (`bg-surface`,
   `text-ink`, `border-signal`, `text-sev-high`, `text-conf-high`,
   `bg-risk-2`, ...), and that refit was never undone — so un-rebuilt
   pages/components reference the SEMANTIC names at least as much as the
   raw palette, often more. Remapping only the raw palette (the literal
   spec instruction) would have left `bg-surface`, `text-ink`,
   `border-signal`, and every severity/confidence/risk class as literally
   undefined Tailwind utilities the moment `tokens.css` was replaced —
   breaking every un-rebuilt page and every shared component this session
   didn't touch, which directly contradicts Part J's "the app stays fully
   functional and reviewable" requirement for the interim page mounting.
   Resolved by remapping BOTH the raw palette and the full session-15
   semantic-name set, inside one clearly fenced "TRANSITIONAL" block,
   explicitly larger in scope than the literal spec text but consistent
   with its stated INTENT. Flagged here per the process rule ("if the spec
   and reality genuinely disagree... say so explicitly"), and in
   `CLAUDE.md`/`DESIGN.md`.

2. **`chartTheme.test.ts`'s "design token light/dark completeness"
   sub-suite was rewritten, not left unmodified.** This is one of the ten
   protected pure-logic test files the session rules say must keep
   passing UNMODIFIED by default. Its token-completeness half, however,
   hard-anchors on `@media (prefers-color-scheme: dark) { :root { ... } }`
   — a block that cannot exist any more under decision #9 (dark as the
   unconditional default, no OS fallback for the initial theme; light
   lives under `:root[data-theme="light"]` instead). This is exactly the
   documented exception ("if a rewrite genuinely requires changing one of
   those modules' behaviour, change its test in the same commit and call
   it out explicitly"): the property the test protects (every token
   declared in one scheme has a matching declaration in the other) is
   preserved byte-for-byte in spirit, only the anchor selector changed
   (from the dark media-query block to the light `data-theme` block, with
   "light" and "dark" roles swapped throughout the test's own variable
   names to match). The subsystem-palette anti-drift half of the same file
   was left completely untouched. Also touched: `SeverityChip.tsx`'s own
   test gained one new assertion (still passes the original two
   unmodified) and `lib/format.ts`'s `SEVERITY_CLASSES`/`healthColor`
   changed their VALUES (not their exported shape) — see the accessibility
   fixes below for why.

3. **`/repos/:id/risk` (redirect #23 of 23) is not a literal `<Navigate>`
   route.** The rebuild spec's section 4.2 lists this session-02 legacy
   share-link path redirecting to `/repos/:id/risk?tab=hotspots`, and its
   own note calls out exactly ONE "pleasant coincidence" (the legacy
   `/overview` path landing on a route now bare-named identically) as
   grounds for skipping a separate redirect route. The new route table
   happens to create the IDENTICAL coincidence for `/risk` too — the new
   real "risk" surface is bare-named "risk", exactly matching this legacy
   path — but the spec's own note doesn't mention this second case.
   Registering a literal second `<Route path="risk">` for the redirect
   alongside the real surface route at the same path is not just
   redundant, it's a genuine routing conflict (React Router can only match
   one element per path; the loser is either unreachable dead code or
   silently shadows the real surface, depending on registration order).
   Resolved by treating this exactly like "/overview" — one real route,
   documented at the route definition in `App.tsx` and verified with a
   dedicated test case (`RepoLayout.redirects.test.tsx`, entry 23) that
   asserts the outcome ("lands on the risk surface, defaulting to
   hotspots") rather than the redirect MECHANISM (a location change),
   since no navigation actually occurs. Flagged as a spec/reality
   discrepancy per the process rule, not silently patched over.

4. **Two real, concrete accessibility failures were found in the LOCKED
   section-3.1 hex values, once actually measured against how a component
   would use them** — not a judgement call about the spec's intent so
   much as a genuine internal contradiction between decision #5 ("palette
   hex values are not negotiable") and rule V6 ("every text/background
   pairing is contrast-checked... at least 4.5:1 for body text, at least
   3:1 for non-text"). `--color-scale-5` (dark scheme) measured 2.84:1 as
   text/border against `--color-bg-elevated` — below even the 3:1 bar.
   `--color-scale-1` (light scheme) measured 3.37:1 — clears 3:1, fails
   4.5:1. `--color-border-strong` (both schemes) measured 1.60:1/1.97:1
   against `--color-bg-elevated` as an interactive-control boundary — the
   exact WCAG 1.4.11 problem session 15's own `--color-border-interactive`
   token existed to solve, for a different palette. Resolved by changing
   component-level USAGE only — `SeverityChip`/`Badge` render severity as
   a solid fill with a per-tier fixed ink rather than an outline; `Input`/
   `Select`/`Button` read a new `--color-border-interactive` token instead
   of `--color-border-strong` — while leaving every locked hex value in
   `tokens.css` completely untouched. Full reasoning and the complete
   measured before/after numbers are in `DESIGN.md`'s "Known Hazards"
   section; this is the "follow reality when spec and reality disagree"
   rule applied at the narrowest possible scope (usage, not values).

## Structural observations noticed, not fixed this session

1. **The mobile header nav wraps tightly at a 360px viewport.**
   Verified with no horizontal overflow (`document.documentElement.scrollWidth
   === 360`, checked with a real Playwright run against the dev server —
   not assumed), so it satisfies the hard "no overflow" requirement, but
   the small-screen nav row (`How Compass Works` / `Glossary` / the
   narrative toggle, all in the header's right cluster) wraps to two and
   three lines rather awkwardly. A future session doing a dedicated
   responsive pass on `AppShell` should collapse this cluster into a
   overflow/hamburger menu below some breakpoint rather than letting every
   item wrap independently — out of scope for a foundation session whose
   job was "must not overflow," not "must look ideal at every width."

2. **`NarrativeBlock`, `FindingItem`, `EvidencePanel`, `GraphCanvas`,
   `ModeSelect`, `DirectoryTreemap`, `CodeCity` were deliberately left
   completely untouched**, including `NarrativeBlock`'s own violet accent
   colour, which rule V1 explicitly names as something to re-theme onto
   `--color-info` — but the rebuild spec's own text assigns that specific
   change to session 2 ("the narrative surface is re-themed onto
   `--color-info` in S2"), not this one. Confirmed this is intentional,
   not an oversight, by re-reading section 3.4's own rule text before
   leaving it alone.

3. **The old top-level `components/Card.tsx` (title/subtitle/action/
   children, sans-serif heading) now coexists with the new
   `components/ui/Card.tsx` (eyebrow/title/action/children, serif
   heading)** — deliberately, since ~18 not-yet-rebuilt pages still import
   the old one and touching their internals is out of this session's
   scope. Delete the old one once sessions 3/4 have migrated every call
   site off it — grepping for `from "../components/Card"` /
   `from "../../components/Card"` (as opposed to `.../ui/Card`) finds
   every remaining reference.

4. **`GET /repos/showcase` was exercised only against a backend that
   wasn't running** (no live Compass API was available while building this
   session) — the landing page's showcase section, submit form, and
   GitHub-repo picker were all verified to render their correct EMPTY/
   pending/error states (no showcase cards shown when the endpoint
   `ERR_CONNECTION_REFUSED`s; the alert banner and submit form still
   render correctly) via a real headless-Chromium run, but the actual
   populated-showcase-card visual (CountUp stats ticking up from real
   `commit_count`/`subsystem_count`/`truck_factor`/`health_score` values)
   was not seen against real data this session. The component code path
   was read carefully against `ShowcaseRepoOut`'s real type and the
   `CountUp` primitive's own behaviour, but this is worth a second,
   backend-connected look before shipping.

5. **Resolved during this same session, not left open**: the first
   verification pass only reached `RepoLayout`'s loading skeleton (no
   backend running). A follow-up pass mocked all eight repo surfaces
   against real API responses (fields copied verbatim from the project's
   own proven `e2e/fixtures.ts`, not re-approximated) via a throwaway
   Playwright script, and navigated into all eight — `overview`, `map`,
   `tour`, `people`, `findings`, `risk`, `structure`, `evolution`. Zero
   uncaught page errors across all eight; the repo header, the 13-stage
   pill strip, the new 8-tab nav, and every `SegmentedControl` (Structure's
   Architecture/Coupling/Impact, Findings' Findings/Security/Hygiene, and
   the rest) rendered and were visually confirmed correct — including the
   `SeverityChip` fill redesign (Known Hazard #1 above) actually rendering
   as a clearly legible solid amber "Medium" chip on the Findings surface,
   and the force-directed Architecture graph correctly colouring its nodes
   from the NEW subsystem palette. The one pre-existing, out-of-scope
   cosmetic item noticed along the way: `ArchitecturePage.tsx`'s own
   "No circular dependencies" copy includes a 🎉 emoji, in violation of
   rule V2 — inherited from before this session (that file is untouched,
   session 4's job), not introduced by it, and not fixed here since fixing
   it would mean editing a repo surface's internals.
