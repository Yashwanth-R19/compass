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

---

# 2026-09-03 — UI rebuild session 2 (explainability spine)

`plan/UI_REBUILD_SESSIONS.md`'s own Session 2 prompt, sections 1-6 plus
CLAUDE.md's engine/formula documentation, is the normative spec this
session implemented: three new backend `/meta/*` endpoints,
`src/content/explainability.ts` + `src/content/methods.ts`,
`ScoreExplainer`, `HonestyNote`, `GlossaryDialog`, `/how-it-works`,
`/methods`, and the `NarrativeBlock` retheme onto `--color-info` flagged
open by session 1's own entry above.

## Judgement calls made, and why

1. **`app/engines/risk.py`'s three risk weights and `app/engines/
   passport.py`'s five difficulty weights were extracted into named
   module-level constants** (`RISK_CHURN_COMPLEXITY_WEIGHT` etc.,
   `DIFFICULTY_SUBSYSTEM_COUNT_WEIGHT` etc.) — the one backend change this
   session made beyond the three new files, and squarely inside decision
   #4's "backend changes are permitted where the UI genuinely cannot
   explain something without them." Before this change those eight
   numbers were inline literals in the formula expressions themselves;
   `GET /meta/formulas`'s entire reason for existing — "if a weight
   changes, this endpoint changes with it" — is structurally impossible
   without a named constant to import. Same values, same order of
   operations, verified by `black`/`ruff`/`mypy` all passing clean and by
   `tests/test_meta.py` asserting the API response equals the constant
   read directly off the module.
2. **The five FACT stages' `engines` list in `GET /meta/pipeline` is a
   small hand-written table** (`_FACT_STAGE_ENGINES` in `app/api/meta.py`),
   not introspected off `app/jobs/stages.py::FACT_STAGES` — that tuple's
   own `Stage.callables` field is deliberately empty for fact stages (its
   own docstring: each one's local state doesn't fit the uniform Engine
   signature, so `run_ingestion_job` runs their bodies inline instead).
   There is nothing to introspect. Transcribed from CLAUDE.md's own
   pipeline diagram (`clone_repo`, `mine_repo`,
   `extract_structural_edges`/`extract_manifests`/
   `extract_declared_dependencies`, `persist_facts`, `scan_history`) —
   the same "hand-written, cited from the authoritative doc" discipline
   the session prompt itself prescribes for stage `description`s.
3. **The `expertise` FormulaGroup's "also measured (not scored)" list
   includes "Changes to this file" even though `DL` (the same
   underlying count) is literally one of the three weighted terms in the
   DOA formula itself.** Section 5.2's own text names exactly this triple
   ("people/DOA — `changes` (DL), `last_touched_at`, `is_stale`") for that
   block. Implemented literally rather than re-interpreted, on the
   reading that the `/expertise` API's `changes` field is displayed as
   supporting evidence alongside an expert assignment, separate from the
   FA/DL/AC contribution rows a live embedding would render — but this is
   a genuine tension in the source spec worth a second look once session
   3/4 actually places `ScoreExplainer` on `PeoplePage`.
4. **`health` and `onboarding_difficulty`'s "also measured" blocks render
   a note only, with no item list** — section 5.2 states plainly that
   `cycle_count`/`hidden_dependency_count` (health) and every
   `difficulty_breakdown` component (onboarding difficulty) ARE scored,
   so listing them under "also measured (NOT scored)" would misrepresent
   them. `FormulaCopyEntry.alsoMeasured` is `undefined` for both; only
   `alsoMeasuredNote` (the clarifying sentence about the two different
   0.60/0.70 thresholds, and about which three of five terms go through
   `norm()`) renders.
5. **`src/lib/copy.ts` and `src/lib/copy.test.ts` were left completely
   untouched**, per decision #11 ("`src/lib/*.test.ts` must keep passing
   untouched"). `src/content/copy.ts` is a one-line `export *` re-export
   instead of a physical move, so "one content module owns every
   user-facing string" (section 5, point 2) is true of the *import
   surface* (`from "../content"` or `from "../content/copy"` both work)
   without touching a protected file for zero functional gain.
6. **`NOT_AI_WRAPPER_POINTS` and `WHAT_COMPASS_DOES_NOT_DO` live in
   `content/explainability.ts`, not `content/methods.ts`**, even though
   they were first drafted there — both belong to `/how-it-works` (Part
   D), and `content/methods.ts`'s own docstring scopes it to `/methods`
   (Part E) content only. Moved before either page was wired up, so
   there's no churn to note beyond this line.
7. **`GlossaryDialog` is a new, self-contained Radix `Dialog` (centered
   modal), not a reuse of the existing `Drawer` (right-edge slide-in).**
   `Drawer`'s own shape is a deliberate design choice for a detail panel
   that shouldn't navigate away from what triggered it; a searchable,
   scannable term list reads better centered, the same shape Aporia-style
   glossary dialogs generally use. Both share Radix's focus-trap/Escape/
   focus-return machinery underneath, so there's no accessibility
   regression from not reusing `Drawer` specifically.
8. **`MethodsPage`'s locked/heuristic/cited status pill does NOT reuse
   `Badge`'s `high`/`med`/`low` severity tones**, even though they were
   the closest three-tone option already in the primitive. Severity tones
   read as an implicit ranking (high worse than low); locked/heuristic/
   cited is a classification, not a ranking, and borrowing severity's
   visual language would wrongly suggest "cited" is somehow better or
   worse than "locked." A small local three-tone treatment
   (`STATUS_CLASS` in `MethodsPage.tsx`) reuses existing semantic tokens
   (`text-heading`/`warning`/`info`) instead.
9. **`CORPUS_REPO_LIST_URL` links to this project's own real GitHub
   remote** (`https://github.com/Yashwanth-R19/compass/blob/main/...`),
   confirmed via `git remote -v` before writing it rather than guessed —
   the one live external link this session added.
10. **`useFormulas`/`usePipeline`/`useWorkedExample` all use plain
    `apiGet`, never `apiGetOrPending`** — none of the three
    `/meta/*` endpoints is scoped to a repo or a run, so the whole
    202-while-pending contract (`_pending_response`, CLAUDE.md's Analysis
    API section) simply doesn't apply to them; `GET /meta/worked-example`
    answers its own "nothing to show yet" case with a 200 `null` body
    instead, which the frontend type (`WorkedExampleResponse | null`)
    already models directly.

## Structural observations noticed, not fixed this session

1. **`HeuristicNote.tsx` (built session 1, listed in that session's own
   "rebuild these" set) still holds its calibration wording as two
   component-local string constants**, not sourced from
   `content/explainability.ts`'s new `CALIBRATION_COPY`. Part C of this
   session names exactly four components to build (`ScoreExplainer`,
   `HonestyNote`, `GlossaryDialog`, `OnboardingPanel`) — `HeuristicNote`
   isn't one of them, and retrofitting a component nobody asked this
   session to touch, purely to satisfy the "no inline copy" rule's
   *spirit*, risked exactly the kind of scope creep `plan/RULES.md`
   warns against. `CALIBRATION_COPY`'s wording was written to be
   reusable here directly (not copied from `HeuristicNote`, but
   compatible with it) — folding the two together is a natural, cheap
   pickup for whichever of session 3/4 next touches `RiskPage`/
   `HealthPage`/`PassportPage` (the only three current call sites).
2. **`ScoreExplainer` and `HonestyNote` have no live embedding on any
   page yet** — by design (Part C: "ready for sessions 3 and 4 to
   place"), their only current consumers are their own test suites. The
   props contract (`ScoreExplainerContribution`/
   `ScoreExplainerAlsoMeasuredValue`) is deliberately generic rather than
   inferred from one specific page's data shape, since there was no real
   caller yet to shape it against — worth a second look once `RiskPage`
   is actually rebuilt, in case the real data shape wants a small
   adjustment.
3. **`ArchitecturePage.tsx`'s 🎉 emoji** (rule V2, flagged by session 1's
   entry above) is still there — still untouched, still session 4's job.
4. **`/meta/formulas` spot-check against the live engine source** (Part
   G's own required step): `RISK_CHURN_COMPLEXITY_WEIGHT = 0.60`
   (`backend/app/engines/risk.py:28`), `MIN_SHARED_REVS = 5`
   (`backend/app/engines/coupling.py:28`), and
   `CYCLE_PENALTY_PER_CYCLE = 6.0` (`backend/app/engines/health.py:19`)
   were each grepped directly and confirmed to match
   `app/api/meta.py::get_formulas`'s corresponding
   `risk_engine_module.RISK_CHURN_COMPLEXITY_WEIGHT`/
   `coupling_engine_module.MIN_SHARED_REVS`/`health.CYCLE_PENALTY_PER_CYCLE`
   reads verbatim (module-attribute reads, never re-typed literals).
5. **`/how-it-works` and `/methods` were verified against a real,
   running dev server with NO backend behind it** (a genuine
   `ERR_CONNECTION_REFUSED` for every `/meta/*` call, via a throwaway
   headless-Chromium Playwright script — not a mock), in both colour
   schemes and at 360px: both pages render fully and coherently with
   every degrade path engaged at once (`pipeline.data` absent →
   `EMPTY_MESSAGES.pipelineUnavailable`; `workedExample.data` absent →
   `EMPTY_MESSAGES.workedExampleUnavailable`, every stage section still
   renders its description with its example line simply omitted) — no
   blank sections, no literal `"undefined"`/`"null"` anywhere in the
   rendered text (checked programmatically, not just by eye), no
   horizontal overflow at 360px. `GlossaryDialog` was separately
   exercised end-to-end (open, type a search term, confirm the list
   filters, confirm `Escape` closes it and focus returns to the trigger
   button) against the same live dev server.

---

# 2026-09-03 — UI rebuild session 3 (surfaces: Overview, Map, Tour, People)

`plan/UI_REBUILD_SESSIONS.md`'s own Session 3 prompt, sections 1-6 plus
CLAUDE.md's engine/formula documentation, is the normative spec this
session implemented: four repo surfaces (`overview`/`map`/`tour`/`people`)
rebuilt against the new design system, replacing session 1's interim
scaffolding mounting for those four, each gaining the explainability
treatment (`InfoTooltip` on every metric name, `ScoreExplainer` on every
score, every applicable honesty statement from section 5.3 placed and
visible).

## Judgement calls made, and why

1. **`GET /meta/formulas` gained a `glossary` group — the one backend
   change this session made, confirmed with the user first.** Session 2's
   own build never added a formula group for the glossary term score
   (`log(1 + occurrences) × (1 + subsystem_spread / total_subsystems)`)
   despite CLAUDE.md section 5.1's table always having listed it, and
   Part C's own instruction to build a `ScoreExplainer` for it presumes a
   live group to read from. Rather than silently deciding this either way
   (touch the backend, or leave the term-score explainer permanently
   degraded to prose), this was surfaced as an explicit question — the
   user chose "add the backend group." Implemented as a small,
   precedented addition (`app/api/meta.py`, `app/engines/glossary.py`'s
   three existing constants, a matching `tests/test_meta.py` case) —
   verified directly (`python -c "import app.api.meta as m; ..."`, since
   this environment has no Docker/`TEST_DATABASE_URL` for a real pytest
   run) that the new group's constants match the engine source exactly,
   and confirmed `ruff`/`black`/`mypy`/`pytest --collect-only` all stay
   clean (528 tests collected, was 527).
2. **DOA's `ScoreExplainer` renders with `contributions: []`, never a
   forced weighted-sum breakdown.** DOA's real formula
   (`3.293 + 1.098×FA + 0.164×DL − 0.321×ln(1+AC)`) has a base offset and
   a SUBTRACTED log term — it does not fit `ScoreExplainer`'s
   `weight × normalizedValue`-summed-to-a-total contribution-bar model at
   all (a "share of total" bar for a term that's actually being
   subtracted would visually claim the opposite of what the arithmetic
   does). Session 2's own DESIGN_NOTES entry flagged exactly this tension
   as open for this session to resolve. Resolved by leaning on items 1-3
   and 6 of the contract (real formula sentence, range note, the NEW
   citation line, and "also measured") rather than forcing a misleading
   numeric breakdown — the alternative (inventing a weight of 1 for two
   "positive-looking" terms and silently dropping the AC term) would have
   shown arithmetic that doesn't reproduce the real formula, which is
   exactly the kind of dishonest degradation this product's whole design
   argues against. The glossary term score (`log(1+occurrences) ×
   (1+spread/total)`, a PRODUCT of two factors, not a sum) has the
   identical problem and got the identical treatment.
3. **`ScoreExplainer` itself gained citation rendering** (a small,
   additive change to a session-2-built, previously-unembedded shared
   component) — session 2's own build read `FormulaGroupOut.citation`
   into nowhere; Part D's "the explainer must say so and carry the
   citation" requirement for DOA has nowhere else to render through,
   since `ScoreExplainer` is "the one generic explainer, never a
   page-local reimplementation" (section 5.2). A new test case
   (`ScoreExplainer.test.tsx`) asserts the citation line appears for a
   `status: "cited"` group and never for a locked one.
4. **Health's own `ScoreExplainer` omits the `calibration` prop
   entirely**, even though `HealthResponse`/`PassportHealth` both carry a
   `calibration` field and the page-level `HonestyNote` still shows it.
   `HealthEngine` has no `BaselineProvider` seam anywhere in its own
   source (no `norm()` call) — showing `ScoreExplainer`'s built-in
   calibration line ("normalized against this repository's own
   values...") for a formula that never normalizes anything through that
   seam would misrepresent it as baseline-aware. `ScoreExplainer`'s own
   docstring already anticipates this ("omit for a formula with no
   baseline-provider seam, e.g. coupling, subsystems") — health joins
   that list.
5. **Overview's language-mix chart now reads
   `data.identity.language_breakdown`** (already inside the single
   `usePassport` payload) instead of the old `HealthPage`'s
   `useRisk()`-derived file-language tally — a genuine simplification
   this merge made possible, not just a token-styling pass: it removes
   an entire extra network request from the page and keeps every section
   gated on the one "onboarding" stage the merged surface's own row in
   table 4.4 specifies, rather than mixing in "risk" stage data that
   happens to already be available by the time "onboarding" finishes.
6. **The run-history sparkline stays outside the passport `StageGate`**,
   unchanged from session 08's placement — it describes PAST runs via its
   own `useRuns`/`useHealthHistory` calls, which have no stage gate of
   their own, so nesting it inside the current run's passport gate would
   make a repo mid-re-analysis lose its OWN visible history for no
   reason.
7. **`ModeSelect.tsx` and `DirectoryTreemap.tsx` were rebuilt onto the
   new design system even though session 1's own Part F component list
   didn't name either one.** Both are Map-surface-exclusive (confirmed by
   grep — nothing outside `pages/onboard/MapPage.tsx`/
   `components/CodeCity.tsx` imports them), so rebuilding them is squarely
   inside "rebuild this surface fully," not scope creep into another
   session's territory; leaving them on session-15-era `slate-*`/`ink-*`
   classes (working only via session 1's transitional remap) would have
   made an otherwise fully-rebuilt Map surface visually inconsistent with
   itself.
8. **A new shared `components/ColorModeLegend.tsx`**, rather than
   generalizing `CodeCity.tsx`'s own local `Legend` component across all
   three map-family renderers. The 2D graph and the treemap share an
   IDENTICAL four-mode set (subsystem/risk/owner/recency); the 3D city has
   a fifth mode ("test vs source") and a height dimension neither of the
   other two has. Forcing one component to cover all three would need a
   prop surface wide enough to cover the union of both shapes, which is
   more complexity than reuse actually buys here — matching the same
   "reuse where the shapes genuinely match, don't force it" judgement this
   codebase already applies elsewhere (e.g. `DirectoryTreemap` IS shared
   verbatim between the map's treemap view and the city's WebGL fallback,
   because those two really do want the identical thing).
9. **`FileDetailPanel` gained an optional `centrality` prop instead of a
   second panel.** Part B requires an `InfoTooltip` on centrality; the
   only place on the Map surface where a single file's own centrality
   value is both available (from `/subsystems`' member rows) and
   contextually relevant is the moment a file node is selected in the
   graph view. `/city` carries no centrality column at all, so `CodeCity`'s
   own calls to this same component simply don't pass the prop —
   confirmed this doesn't regress the "do not add a second file-detail
   panel" rule, since it's the same component, same file, just one more
   optional field one of its two callers can supply.
10. **`PeoplePage.test.tsx`'s privacy fixtures deliberately embed a real
    `@` in every masked-email field**, rather than leaving those fields
    empty or omitting them. A test asserting "no `@` in the DOM" against
    fixtures that never contained one anywhere would pass whether or not
    the component actually avoids rendering the field — it would prove
    nothing. Building the fixture to make a leak visible IF one were ever
    introduced is what makes this test load-bearing rather than
    decorative.

## Structural observations noticed, not fixed this session

1. **`HeuristicNote.tsx`'s own inline calibration-wording constants**
   (flagged as an open pickup by session 2's own DESIGN_NOTES entry) are
   now fully bypassed on the Overview surface — `OverviewPage.tsx` uses
   `HonestyNote`/`CALIBRATION_COPY` exclusively for both the difficulty
   and health calibration statements, and no longer imports
   `HeuristicNote` at all. `HeuristicNote.tsx` itself was not touched or
   deleted — `RiskPage`/`BenchmarkPage` (session 4's scope) still import
   it, so removing it now would break surfaces this session doesn't own.
   Whether it should be deleted entirely once session 4 also migrates off
   it, or kept as a distinct, simpler primitive, is worth a decision next
   session, not this one.
2. **`ArchitecturePage.tsx`'s 🎉 emoji** (rule V2, flagged by sessions
   1 and 2's own entries) is still there — still untouched, still session
   4's job; this session had no reason to open that file at all.
3. **The Overview difficulty bar's per-segment width still uses the raw
   `weight × normalized` fraction of the bar, unscaled against the
   segments' own sum** (inherited unchanged from the pre-rebuild
   `PassportPage.tsx` — this session only renamed tokens/classes on that
   specific bar, never touched its width formula). A repo whose five
   contribution products sum well under 1.0 (as the fixture used for this
   session's own manual verification does — see below) renders a bar
   that reads as more full than the ScoreExplainer's own arithmetic
   directly under it would suggest at a glance. Not a correctness bug
   (the ScoreExplainer's real numbers are right there, one scroll below),
   but a minor visual-precision gap worth a follow-up if a future session
   is already touching this card.
4. **`pages/repo/{Overview,Map,Tour,People}SurfacePage.tsx` are now
   trivial one-line pass-throughs** to the real components under
   `pages/onboard/`, matching the precedent `PeopleSurfacePage.tsx`
   already set in session 1 (the one surface with no merge to switch
   between). The other four (`Findings`/`Risk`/`Structure`/
   `EvolutionSurfacePage.tsx`) still contain session 1's `?view=`/`?tab=`/
   `?category=` scaffolding logic — session 4's job to replace, following
   this same pattern.

## Verification

- `npm run typecheck` / `npm run lint` / `npm run test:run` / `npm run
  build` / `npm run format:check`: all clean throughout — checked after
  each of the four surfaces individually, not just once at the end, to
  keep failures attributable to the change that caused them. Final state:
  **162 tests, 24 files, all passing** (was 159/23 after session 2; +3
  new `PeoplePage.test.tsx` cases, +1 new `ScoreExplainer.test.tsx`
  case), `CodeCity-*.js` still a separate ~916KB chunk from `index-*.js`.
- Backend: `ruff check app tests` / `black --check app tests` / `mypy
  app/engines app/baseline app/languages` all clean; `pytest
  --collect-only` — **528 tests collected, 0 errors** (was 527 after
  session 2; +1 new `test_meta.py` case, skipped at run time in this
  environment for the same documented Docker/`TEST_DATABASE_URL` reason
  every prior session's backend tests were).
- Manual: a real dev server driven by a throwaway headless-Chromium
  Playwright script (mocked backend, fixture shapes lifted from the
  project's own proven `e2e/fixtures.ts` plus this session's own
  additions for `/glossary`, `/runs`, `/health`, and `/meta/formulas`),
  covering all four rebuilt surfaces, in both colour schemes and at
  360px, plus one `prefers-reduced-motion: reduce` pass: zero uncaught
  page errors (the only console errors observed were the expected
  `/auth/me` 401s `useMe()` treats as "logged out", not a real failure);
  `InfoTooltip` buttons confirmed present and a `ScoreExplainer` confirmed
  expandable on Overview; the Map graph's hidden-dependency edge
  (amber/thicker/dashed) confirmed rendering for a synthetic
  coupled-but-not-imported subsystem pair; the 3D city confirmed
  rendering real extruded building geometry with shadows (screenshotted
  against an enlarged, 45-file synthetic fixture, not just the tiny
  shared fixture, specifically to make the skyline visually legible);
  Tour's glossary panel confirmed opening as a genuine SIDE panel with
  the stepper still visible alongside it, not a full-page swap; People's
  rendered DOM confirmed to contain zero `@` characters despite every
  fixture's masked-email fields containing one, in both colour schemes;
  every one of the four surfaces confirmed at `document.documentElement.
  scrollWidth === 360` with no horizontal overflow, in both colour
  schemes. Not verified against a real, running backend (no live Compass
  API was available while building this session, matching sessions 1 and
  2's own documented limitation) — the populated-data visuals (real
  showcase-style numbers, not synthetic fixture values) are worth a
  second, backend-connected look before shipping, same caveat session 1's
  own entry already logged for the landing page's showcase cards.
