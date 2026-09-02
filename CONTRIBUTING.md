# Contributing to Compass

Thanks for looking at this. Compass was built as a sixteen-session solo
project with a deliberately strict internal discipline — this document is
what you need to work *with* that discipline instead of against it.

## Before you touch anything

Read, in order:
1. `README.md` — what this is and why.
2. `ARCHITECTURE.md` — how it actually works.
3. `CLAUDE.md` — the exhaustive operational reference: every table, every
   engine, every named constant and why it has the value it has. This is
   the document that will actually answer "why does this code do it this
   way" nine times out of ten. Search it before asking.
4. `plan/RULES.md` — the rules every build session followed. Sections 3
   (locked vs. heuristic numbers), 5 (Facts vs. Insight), and 12
   (anti-alert-fatigue) matter most for almost any change you'll want to
   make.

## The rules that matter most

**Never change a locked formula.** `coupling_degree` and `risk_score`'s
exact weights (0.60/0.25/0.15) are locked — verbatim, in a code comment,
with a dedicated test asserting the exact weights. You may improve how an
*input* is measured (session 07 did exactly this with recency-weighted
churn), but never the formula itself. If you think a weight is wrong, open
an issue and make the case — don't just change the number.

**Every heuristic value is a named module-level constant, never an inline
literal**, with a comment stating it's heuristic (not locked) and why that
value was chosen. Grep for `HEURISTIC` in `backend/app/engines/` to see the
existing pattern before adding a new one.

**Facts vs. Insight is not optional.** A new table that stores anything
mined from the repository itself (needs the clone) is a Facts table — add
it to `wipe_facts` and wire it into `persist_facts`, or a re-analysis will
silently duplicate rows forever. A new table that stores something an
engine computes is Insight — it must carry `analysis_run_id`
(`ON DELETE CASCADE`) and be added to `prune_run`, or LRU eviction will
never clean it up.

**Every engine is a pure function.** No git, no network, no filesystem, no
`datetime.now()` (read a *stored* timestamp instead). If your change needs
any of those, it doesn't belong in `app/engines/`.

**No wall of warnings, ever.** Every finding-emitting engine caps how many
findings it emits and reports an honest "showing N of M" when the cap
engages. `FindingsRankEngine` is the one place a global cross-category rank
gets assigned — nothing else re-sorts, and the frontend never re-sorts
either. See `plan/RULES.md` §12 before adding a new finding category.

## Workflow

```bash
# Backend
cd backend
python -m venv .venv && .venv/Scripts/activate    # or source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
pytest -q -rs                 # needs Docker running, or set TEST_DATABASE_URL
ruff check app tests
black --check app tests
mypy app/engines app/baseline app/languages   # the ONE scoped mypy target — do not widen it

# Frontend
cd frontend
npm install
npm run typecheck
npm run lint
npx vitest run
npm run build
```

`pip install pre-commit && pre-commit install` wires `ruff`/`black`/
`prettier` into `git commit` automatically.

**Never use `-uall` on `git status` on this repo** — it's slow on a project
this size for no benefit. Always verify Docker DB tests actually *ran*
(check the summary for `skipped` — a skip due to no Docker still exits 0,
which can silently mean nothing was verified).

## Adding a migration

One Alembic migration per logical change. Generate with `alembic revision
--autogenerate -m "..."`, then **read the generated file line by line**
before applying — autogenerate misses server defaults, doesn't know about
Postgres native enum changes, and will happily emit a `DROP TABLE` for a
table it doesn't recognise. Adding a `NOT NULL` column to a populated table
needs a `server_default` (set then dropped in the same migration — see any
recent migration in `backend/alembic/versions/` for the pattern). Always
verify `alembic upgrade head && alembic downgrade -1 && alembic upgrade
head` round-trips cleanly against a **disposable** database — never your
real `DATABASE_URL`.

## Adding a new engine

1. Implement `Engine.run(self, ctx: RunContext, session: Session) -> dict`
   in `app/engines/your_engine.py`, following the contract in
   `ARCHITECTURE.md`.
2. Register it in the right stage's `callables` tuple in
   `app/jobs/stages.py` — order is load-bearing if a later engine in the
   same stage depends on this one's output.
3. If it emits findings: set `signature` via
   `app/engines/signature.py::finding_signature`, cap the count, and add
   your category to the table in `CLAUDE.md`'s "Every finding-emitting
   engine must set `signature`" section.
4. Update the stage gating map in `app/api/analysis.py::_pending_response`
   and the frontend's stage label map if you added a new stage name.
5. Write a determinism test (same input twice, byte-identical output) and
   a small-repo edge case (0/1 commits, whichever applies).
6. Update `CLAUDE.md`'s "Engines" section and `plan/STATE.md`'s convention
   if you're following the session-based build log.

## Frontend conventions

- `frontend/src/api/types.ts` hand-mirrors the backend's Pydantic schemas —
  no codegen. Add the type in the same change as the backend schema.
- Every user-facing sentence derived from a backend enum lives in
  `lib/copy.ts`'s template maps — never constructed inline in a page
  component. There's an exhaustiveness test; keep it passing.
- Every page must work in both light and dark `prefers-color-scheme`. This
  has held since session 1 — don't be the change that breaks it.
- New UI reaches for the design system's semantic tokens
  (`bg-surface`, `text-ink-muted`, ...) and `components/ui/` primitives —
  never a bare Tailwind `slate-*`/`indigo-*` class or a hand-picked hex
  colour. `lib/chartTheme.ts` is the one source for any new
  chart/graph/canvas colour.

## Security

- Never log, return, or store a raw secret — GitHub tokens, database URLs,
  scanned credential values. If you're unsure whether something counts,
  treat it as one.
- The GitHub Actions workflow repository is public by design (free
  unlimited Actions minutes) — assume every line any workflow prints is on
  the public internet, and route anything that touches a credential
  through `app/jobs/log_redaction.py`.
- `validate_repo_url`'s SSRF guardrails (https-only, `github.com`/
  `gitlab.com` only, public-IP-only resolution) are extended, never
  weakened, by anything that touches URL handling.

Found a real security issue? Please don't open a public issue — see
`DEPLOY.md`'s contact info, or reach the maintainer directly.

## Commit and PR expectations

- Every existing test still passes. Never delete, skip, or weaken a test to
  make a change land — if a test now fails, either the change is wrong, or
  the test encodes something now genuinely obsolete, and that's worth a
  sentence in the PR description either way.
- Keep the diff scoped to what the PR is actually about. This codebase has
  strong internal consistency because sixteen build sessions each stayed in
  their own lane — don't "improve" an unrelated engine while you're in the
  neighbourhood; open a separate PR instead.
- If you touched anything the schema/engine/stage-list docs above describe,
  update `CLAUDE.md` in the same PR. A stale `CLAUDE.md` is worse than a
  short one, because the next contributor will trust it completely.
