# Compass

Compass mines a Git repository's full commit history and computes deterministic,
reproducible intelligence about it — hidden change-coupling, calibrated bug-risk,
architecture, and security findings — the way an AI code assistant structurally
cannot, because that signal lives only in history, not in the current file tree.

See `master-context.md` at the repo root for the full design rationale.

## Layout

- `backend/` — FastAPI + SQLAlchemy + Alembic API and mining/analysis engine.
- `frontend/` — React + TypeScript viz shell (built starting Release A6).

## Backend quickstart

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e ".[dev]"
cp .env.example .env          # fill in DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload
```

## Status

Release A in progress: ingestion pipeline + job system + Change-Coupling groundwork.
