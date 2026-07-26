# Compass

Compass mines a Git repository's full commit history and computes deterministic,
reproducible intelligence about it — hidden change-coupling, calibrated bug-risk,
architecture, and security findings — the way an AI code assistant structurally
cannot, because that signal lives only in history, not in the current file tree.

See `master-context.md` at the repo root for the full design rationale.

## Layout

- `backend/` — FastAPI + SQLAlchemy + Alembic API and mining/analysis engine.
- `frontend/` — React + TypeScript + Tailwind viz shell (TanStack Query, react-router,
  react-force-graph-2d, recharts).

## Backend quickstart

Requires a Postgres database (e.g. a free [Neon](https://neon.tech) project).

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; source .venv/bin/activate on Unix
pip install -e ".[dev]"
cp .env.example .env          # fill in DATABASE_URL (Postgres/Neon)
alembic upgrade head
uvicorn app.main:app --reload # http://localhost:8000
```

Run the test suite. Tests never touch the real `DATABASE_URL` — they run
against an ephemeral Postgres container (Docker must be running), or
`TEST_DATABASE_URL` if Docker isn't available (see `backend/CLAUDE.md`):

```bash
pytest
```

## Frontend quickstart

```bash
cd frontend
npm install
cp .env.example .env          # VITE_API_URL, defaults to http://localhost:8000
npm run dev                   # http://localhost:5173
```

The frontend expects the backend above to be running at `VITE_API_URL`. Submit
a `github.com` or `gitlab.com` repo URL on the home page; it polls the ingestion
job to completion and routes to the repo dashboard (Overview / Coupling /
Architecture / Risk).

`npm run build` type-checks and produces a production bundle in `frontend/dist/`.

## Development setup

This repo uses `ruff` + `black` + `mypy` (backend) and `oxlint` + `prettier`
(frontend), wired together with [pre-commit](https://pre-commit.com):

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on `git commit`. To check everything by hand:

```bash
pre-commit run --all-files
```

See `backend/CLAUDE.md` for the full lint/format/typecheck/test command
reference, and how to write a new database-backed test.

## Status

Release A complete: ingestion pipeline, job system, Change-Coupling +
Architecture + hidden-dependency-overlay engines, heuristic Risk + composite
Health engines behind a swappable `BaselineProvider`, a unified ranked
Findings stream, and a working React dashboard wired end-to-end against the
API. The project is now moving to a dual-mode (Onboard + Audit) platform —
see `COMPASS_PLAN.md` for the roadmap and `master-context.md` §12 for the
six-stage build plan.
