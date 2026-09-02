from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import get_db
from app.db.models import AnalysisRun, AnalysisRunStatus
from app.db.storage import NEON_FREE_TIER_LIMIT_BYTES, get_database_size_bytes

router = APIRouter()


def _migration_version(db: Session) -> str | None:
    """Reads Alembic's own version-tracking table directly rather than
    shelling out to ``alembic current`` -- one plain SELECT, safe to run on
    every health check. Returns ``None`` on a database with no migrations
    applied yet (shouldn't happen against a real deployment, but this
    endpoint must never 500 over it)."""
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except ProgrammingError:
        db.rollback()
        return None


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Hit by the keep-alive ping every 10 minutes forever (Render's free
    tier spins down after 15 minutes idle, see DEPLOY.md) -- kept
    deliberately cheap (session 16, Part D extends this with a handful of
    single-row/single-value reads, still no joins, still no per-table
    breakdown -- that heavier introspection lives at ``GET /internal/storage``
    instead, admin-gated and not on this 10-minute-forever hot path).
    """
    db.execute(text("SELECT 1"))

    active_runs = (
        db.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(AnalysisRun.status == AnalysisRunStatus.running)
        )
        or 0
    )
    storage_bytes = get_database_size_bytes(db)

    return {
        "status": "ok",
        "version": settings.COMPASS_VERSION,
        "db": "ok",
        "migration_version": _migration_version(db),
        "worker_mode": settings.COMPASS_WORKER_MODE,
        "active_runs": active_runs,
        "storage_bytes": storage_bytes,
        "storage_limit_bytes": NEON_FREE_TIER_LIMIT_BYTES,
        "storage_headroom_bytes": NEON_FREE_TIER_LIMIT_BYTES - storage_bytes,
    }
