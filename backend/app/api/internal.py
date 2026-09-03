"""Admin-only operational endpoints (session 16, Part D) -- both gated by
``app/auth/admin.py::require_admin_token``, the same shared secret
``POST /internal/runs/{id}/pregenerate-narratives`` (session 12) already
uses. Neither is ``/repos/{``-shaped, so neither is part of
``test_access_control.py``'s repo-access sweep -- these aren't repo-scoped at
all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.limits import get_rejection_counts
from app.auth.admin import require_admin_token
from app.db.base import get_db
from app.db.models import AnalysisRun, AnalysisRunStatus, AnalysisStage, Repo, StageStatus, User
from app.db.storage import get_storage_report

router = APIRouter()


@router.get("/internal/storage")
def get_storage(db: Session = Depends(get_db), _admin: None = Depends(require_admin_token)) -> dict:
    """Per-table sizes, total usage, and headroom against the 0.5 GB Neon
    free-tier limit (``app/db/storage.py``) -- what the manual checklist and
    ``app/jobs/eviction.py``'s trigger both read."""
    report = get_storage_report(db)
    return {
        "total_bytes": report.total_bytes,
        "limit_bytes": report.limit_bytes,
        "headroom_bytes": report.headroom_bytes,
        "fraction_used": report.fraction_used,
        "tables": [{"name": t.name, "total_bytes": t.total_bytes} for t in report.tables],
    }


def _percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile over an already-sorted list -- the same
    technique ``app/engines/hygiene.py``/``app/engines/expertise.py`` already
    use for their own within-run percentiles, applied here across every
    stage's historical durations instead of one run's file metrics."""
    if not sorted_values:
        return 0.0
    rank = max(1, round(p / 100 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


@router.get("/internal/stats")
def get_stats(db: Session = Depends(get_db), _admin: None = Depends(require_admin_token)) -> dict:
    """Counts, per-stage run-duration percentiles (p50/p95), per-stage
    failure rates, and in-process rate-limit rejection counts.

    Stage timing is a QUERY, not new instrumentation (session 16's own
    prompt) -- ``analysis_stages.started_at``/``finished_at`` have been
    stamped by ``app/jobs/stages.py::stage()`` on every single stage
    transition since session 01; this endpoint is the first thing to
    actually read that history back in aggregate.
    """
    repo_count = db.scalar(select(func.count()).select_from(Repo)) or 0
    showcase_count = (
        db.scalar(select(func.count()).select_from(Repo).where(Repo.is_showcase.is_(True))) or 0
    )
    user_count = db.scalar(select(func.count()).select_from(User)) or 0
    run_counts_by_status: dict[str, int] = {}
    for status in AnalysisRunStatus:
        run_counts_by_status[status.value] = (
            db.scalar(
                select(func.count()).select_from(AnalysisRun).where(AnalysisRun.status == status)
            )
            or 0
        )

    stage_rows = db.execute(
        select(
            AnalysisStage.name,
            AnalysisStage.status,
            AnalysisStage.started_at,
            AnalysisStage.finished_at,
        ).where(AnalysisStage.status.in_((StageStatus.done, StageStatus.failed)))
    ).all()

    durations_by_stage: dict[str, list[float]] = {}
    outcomes_by_stage: dict[str, dict[str, int]] = {}
    for name, status, started_at, finished_at in stage_rows:
        outcomes = outcomes_by_stage.setdefault(name, {"done": 0, "failed": 0})
        outcomes[status.value] += 1
        if status == StageStatus.done and started_at is not None and finished_at is not None:
            durations_by_stage.setdefault(name, []).append(
                (finished_at - started_at).total_seconds()
            )

    stage_stats: dict[str, dict[str, float | int]] = {}
    for name, outcomes in outcomes_by_stage.items():
        durations = sorted(durations_by_stage.get(name, []))
        total = outcomes["done"] + outcomes["failed"]
        stage_stats[name] = {
            "n": total,
            "failure_rate": (outcomes["failed"] / total) if total else 0.0,
            "p50_seconds": _percentile(durations, 50),
            "p95_seconds": _percentile(durations, 95),
        }

    return {
        "counts": {
            "repos": repo_count,
            "showcase_repos": showcase_count,
            "users": user_count,
            "runs_by_status": run_counts_by_status,
        },
        "stage_stats": stage_stats,
        "rate_limit_rejections": get_rejection_counts(),
    }


__all__ = ["router"]
