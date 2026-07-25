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

Run the test suite (hits the real `DATABASE_URL`, no mocking layer — see
`backend/CLAUDE.md` for why):

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

## Status

Release A complete: ingestion pipeline, job system, Change-Coupling +
Architecture + hidden-dependency-overlay engines, heuristic Risk + composite
Health engines behind a swappable `BaselineProvider`, a unified ranked
Findings stream, and a working React dashboard wired end-to-end against the
API. Corpus-based calibration (Release C) and portfolio/security features
(Releases B–D) are not built yet — see `master-context.md` §11 for the full
roadmap.
