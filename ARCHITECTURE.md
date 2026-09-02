# Architecture

This is the "how does it actually work" document. `README.md` is the pitch;
`CLAUDE.md` is the exhaustive, session-by-session reference with every
design decision's rationale; this sits between them — enough detail to
actually understand the system, organized by concept rather than by the
order it was built in.

## The one decision everything else follows from: Facts vs Insight

Every table in this schema is one of two kinds.

**Facts** — `repo_paths`, `commits`, `files`, `dependencies`, `symbols`,
`repo_manifests`, `secret_hits`, `dependencies_declared`. Requires the
clone. Deterministic given `(repo_url, head_sha)`. Keyed by `repo_id` only.
Wiped and fully replaced whenever a fresh `git ls-remote` shows the remote's
`head_sha` has actually changed — never touched otherwise. `repo_paths` is
the one deliberate exception: it's append-only forever, because every
Insight row below references a path by its integer id, and those ids have
to survive a Facts replace or every older analysis run's data would
cascade-delete the moment the repository got new commits.

**Insight** — `coupling`, `module_coupling`, `subsystems`, `file_metrics`,
`contributors`, `truck_factor`, `findings`, `health`, `tour_stops`,
`glossary_terms`, `repo_passport`, `hygiene_events`, `vulnerabilities`,
`snapshots`, `narratives`, and more. Requires only the database — produced
by pure-function engines, never git/network/filesystem. Keyed by
`analysis_run_id`, not `repo_id` alone (every table also carries a
denormalised `repo_id` for cheap scoped queries, but `repo_id` alone is
never a sufficient filter — the table holds every past run's rows too). A
re-analysis creates a brand-new `analysis_runs` row rather than overwriting
the old one; old runs stay queryable, diffable (run-vs-run compare), and
independently prunable (LRU storage eviction).

This split is why re-analysing an unchanged repository is nearly instant
(Facts are reused, only Insight recomputes), why progressive reveal works at
all (each stage commits independently, so the frontend can render results
stage-by-stage instead of waiting for the whole pipeline), and why
time-travel/compare/eviction all fall out of the same design instead of
needing bespoke machinery each.

## The ingestion pipeline

```
POST /repos
  → SSRF/visibility/size guardrails, rate limits, per-user cap
  → find-or-create the `repos` row, dispatch the job
  → returns {repo_id, job_id} immediately

run_ingestion_job(repo_id, job_id)          — transport-agnostic; called the
                                               same way whether it runs inline
                                               (FastAPI BackgroundTasks) or on
                                               a GitHub Actions worker
  → create an `analysis_runs` row + pre-create every stage row as "pending"
  → git ls-remote (no clone) to check whether Facts can be reused
  → IF unchanged: skip straight to Insight (near-instant re-analysis)
  → ELSE, five FACT stages, each committed independently:
      clone → mine → structure → persist_facts → secrets
      (the clone is deleted right after "secrets" — everything after this
       point is pure DB reads/writes, no filesystem access at all)
  → eight INSIGHT stages, in a FIXED, load-bearing order, each committed
    independently (a stage may run several engines in sequence):
      coupling → subsystems → architecture → risk → knowledge
      → onboarding → security → rank
  → on success: run → ready, repos.current_run_id moves to it, the
    previous current run → superseded (its rows are untouched)
  → on failure: only the failing stage/run are marked failed —
    repos.current_run_id is NEVER touched, so a bad re-analysis never
    blanks out a repository that already had a good run
```

**The commit-per-stage-transition is the entire mechanism behind
progressive reveal.** `GET /repos/{id}/status` is a cheap poll (one row
lookup, one stage-table query) the frontend hits every 1.5s; because each
stage commits the moment it finishes, that endpoint can render "Coupling ✓,
Subsystems ✓, Architecture (running)…" while the pipeline is still
mid-flight, instead of the whole page staying blank until everything
finishes.

**A stage may run several engines.** "subsystems" runs `SubsystemEngine`
then `ModuleCouplingEngine` (the second needs the first's partition
already written); "architecture" runs `ArchEngine` → `EntryPointEngine` →
`OverlayEngine`; "onboarding" runs five engines in sequence, ending with
`PassportEngine`, which embeds `HealthEngine`'s just-written row into its
own output. This ordering is the single most common place a change to this
pipeline can silently break something — see `app/jobs/stages.py`'s own
docstring for exactly why each ordering is load-bearing.

**One stage is `optional=True`: "security."** Its OSV.dev lookup is the one
deliberate network-touching exception inside the otherwise pure-DB Insight
half — an OSV outage fails only that stage, never the whole run, so a
third-party API hiccup can never turn a working analysis into a failed one.

## The engine contract

Every analysis engine (`backend/app/engines/`) implements:

```python
class SomeEngine(Engine):
    def run(self, ctx: RunContext, session: Session) -> dict: ...
```

- **Pure function over persisted facts.** No git, no network, no
  filesystem, no clock-dependent behaviour beyond reading a stored
  timestamp. This is the literal code behind "why not AI": determinism by
  construction, not by discipline.
- **Never commits or rolls back** — the caller (`run_ingestion_job`) owns
  the transaction.
- **Never deletes.** A fresh `run_id` has no rows of its own by
  construction (that's what the Facts/Insight split guarantees), so "an
  engine never issues a `DELETE`" is a structural property, not a
  convention someone could quietly violate.
- **Reads another engine's output filtered by `analysis_run_id ==
  ctx.run_id`, never `repo_id` alone** — the single most common correctness
  bug class in a codebase shaped like this one, since every Insight table
  holds every past run's rows too.
- **Deterministic.** Any iteration over a set/dict that affects output
  order is explicitly sorted; any randomised algorithm (Louvain community
  detection) is seeded with a named constant specifically because
  determinism is a product claim, not an implementation detail.

`RunContext` (`app/engines/context.py`) is a small per-run cache — the
dependency graph, cycle list, hidden-dependency list, path maps — memoised
once per `(repo_id, run_id)` so three different engines that each need the
dependency graph don't each rebuild it. It is a cache, never a source of
truth, and never a side channel for one engine to pass data to a later one;
if engine B needs engine A's output, B reads A's *persisted* rows.

## The flagship computation: change coupling

For every commit, take its changeset (the set of files touched). Drop
changesets over 30 files (merges, mass reformats — pure noise). For every
file pair with enough shared history, compute the one locked formula in
this codebase:

```
coupling_degree(A, B) = shared_revs(A, B) / min(revs(A), revs(B))
```

Then overlay that against the structural (import) graph: a pair with high
coupling and *no* import edge in either direction is a **hidden
dependency** — the flagship finding. Module-level coupling (`app/engines/
module_coupling.py`) extends the identical formula to directory/subsystem
granularity, computed directly from module-grain commit changesets — never
by aggregating file-pair rows, which is mathematically invalid for this
ratio (a loud comment and a dedicated regression test both guard against
that specific wrong-but-plausible implementation).

## Baseline calibration — the injected seam

`RiskEngine`, `HygieneEngine`, and `PassportEngine` never compute a
min/max normalization themselves — they depend on an injected
`BaselineProvider` (`app/baseline/base.py`) with two methods:
`percentile(...)` and `risk_normalizer(...)`. Three implementations share
that interface: `HeuristicBaseline` (a per-repo min-max scaler, no
external data), `SeedBaseline`, and `CorpusBaseline` (reads percentile
breakpoints seeded from ~30 curated repositories, with a cell-size gate
that widens or falls back rather than trusting a thin cell). Which one is
active is one setting, `COMPASS_BASELINE_PROVIDER`, read per-job — swapping
providers changed zero lines in any engine, which is the entire point of
the seam existing before the corpus did.

## Security & supply-chain

Two independent capabilities inside the "security" stage:

- **Secret scanning** (`app/security/scanner.py`) streams `git log -p`
  over the *entire* history — not just the current tree — through ~25
  trimmed gitleaks-pattern rules, gated by a cheap keyword pre-filter
  before any regex runs (load-bearing for the time budget, not an
  optimization). Never stores a raw secret value: only a salted
  fingerprint and a fixed-length redacted preview. `still_in_head` is
  computed by a second pass over the checked-out tree and matched by
  `(rule_id, fingerprint)` — deliberately not inferred from "does the file
  still exist," since a file can survive while the one line with the
  secret was removed from it.
- **Dependency vulnerabilities** (`app/security/osv.py`) parses four
  manifest formats into structured `(ecosystem, package, version)` rows,
  batches them against OSV.dev, and caches every fetched advisory forever
  in a table that is neither Facts nor Insight — an advisory's content is
  the same fact regardless of which repository or run asks about it.

## Storage eviction

`app/jobs/eviction.py`, wired into the existing 15-minute reaper cron
(no separate always-on process), keeps a Neon free tier's 0.5 GB limit from
ever being exceeded, in order:

1. **Never**: a showcase repository, a repository's current run, or any run
   younger than 7 days.
2. Prune superseded runs beyond the most recent 3 per repository (their
   Insight rows only — via `prune_run`, implemented since the Facts/Insight
   split, unused until this wiring).
3. If still above the high-water mark, wipe **Facts** (not Insight) for
   repositories unvisited in 30 days — the repository row and its current
   run's computed metrics stay fully readable; only a revisit needs a fresh
   clone.
4. `VACUUM` (never `VACUUM FULL`, which locks the table exclusively) so
   Postgres actually returns the freed pages.

## API access control

One reusable FastAPI dependency, `require_repo_access`, gates every
repo-scoped endpoint: a public repo is readable by anyone; a private repo
only by its owner or a valid share link scoped to one specific run; a
pinned showcase repository is readable by anyone regardless of its own
`is_private` flag. A dedicated test enumerates every route whose path
contains `/repos/{` and asserts it depends on this function — the guard
against a session adding a new endpoint and silently forgetting the check.

Every analysis-result endpoint follows one contract: the stage that
produces its data hasn't reached `done`/`skipped`/`failed` for the resolved
run → **HTTP 202** (`{"stage": ..., "status": ...}`); done with zero rows →
**HTTP 200** with an empty body (genuinely computed, genuinely empty); no
run exists at all → **404**. Conflating "not computed yet" with "computed
and empty" is the single most common way progressive reveal ends up
feeling broken in a system like this, so one shared response helper
enforces the distinction everywhere instead of leaving it to sixteen
sessions' worth of individual handlers to each get right.

## Frontend

React + TypeScript + Vite, TanStack Query for all server state. Two
primary modes (`Onboard`/`Audit`) live under `/repos/:repoId/{mode}/*`, with
the active mode read from the URL itself (not component state) so a hard
refresh or a pasted link always lands correctly. Every result hook returns
a `FetchResult<T>` — `{kind: "data"}` or `{kind: "pending", stage, status}`
— and every page renders it through one shared `StageGate` component,
which is the only place in the whole frontend that turns
pending/error/empty/data into branching logic.

Three visualization layers share one colour system
(`lib/subsystemColors.ts`, colourblind-verified against three simulated
vision types): the 2D force graph (coupling/architecture), the treemap/map,
and the 3D code city (`react-three-fiber`, lazy-loaded into its own build
chunk so a visitor who never opens it never downloads `three.js`) — a
subsystem is the same colour in all three, which is what makes the product
read as one coherent tool rather than four visualizations stapled
together.

## Deployment shape

Render (API) + Vercel (frontend) + Neon (Postgres), all free tier, plus a
GitHub Actions worker for the actual mining. `POST /repos` dispatches a
`repository_dispatch` event carrying only `repo_id`/`run_id` — no clone
URL, no token, no credential of any kind reaches that payload — the worker
resolves everything else itself from its own `DATABASE_URL`. If the
dispatch call itself fails (a GitHub outage, a misconfigured PAT), the job
falls back to running inline in the same process rather than leaving the
submission stuck. `DEPLOY.md` has the complete, literal setup steps.

---

For the full session-by-session build history, every named constant's
exact value and rationale, and the complete schema reference, see
`CLAUDE.md` — this document is deliberately the shorter, concept-first
version of the same system.
