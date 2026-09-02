"""``GET /repos/{repo_id}/timeline`` (session 13, Part D) -- the evolution
scrubber's data source. A self-contained feature gets its own router file,
matching the precedent ``app/api/{narrative,share}.py`` already set, rather
than growing the already-large ``app/api/analysis.py`` further.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_repo_access
from app.db.base import get_db
from app.db.models import AnalysisStage, Repo, Snapshot, StageStatus
from app.db.runs import resolve_run_id
from app.schemas.timeline import (
    TimelineBounds,
    TimelineContributorShareOut,
    TimelineCouplingPairOut,
    TimelineHotspotOut,
    TimelineMetricBounds,
    TimelineResolution,
    TimelineResponse,
    TimelineSnapshotOut,
)

router = APIRouter()

TIMELINE_COVERS = [
    "files",
    "commits",
    "contributors",
    "churn",
    "coupling_pairs",
    "churn_ranked_hotspots",
]
TIMELINE_NOT_COVERED = (
    "This timeline is history-derived only. Complexity, dependency cycles, and the subsystem "
    "partition are NOT sampled at these historical points -- doing so would require checking "
    "the repository out at each old revision, which Compass does not do. The file ranking above "
    "is churn-ranked, not the full risk formula (churn * complexity + coupling + commit count): "
    "complexity at a past revision was never measured."
)
"""Part D's required, explicit not_covered note -- surfaced verbatim by the
frontend (Part F: "do not bury this")."""


def _resolve_run_or_404(repo: Repo, run_id: uuid.UUID | None, db: Session) -> uuid.UUID:
    resolved = resolve_run_id(repo, run_id, db)
    if resolved is None:
        raise HTTPException(status_code=404, detail="No analysis run exists for this repo yet.")
    return resolved


def _pending_response(run_id: uuid.UUID, stage_name: str, db: Session) -> JSONResponse | None:
    """A small local copy of app/api/analysis.py's own ``_pending_response``
    -- same 202-while-pending / done-or-skipped-or-failed-is-terminal gate
    (see that module's docstring for the full reasoning) -- rather than
    importing a private, underscore-prefixed helper across modules. Same
    "a tiny, deliberate local copy beats a cross-module private import"
    precedent app/engines/hygiene.py's ``_nearest_rank_percentile`` already
    set relative to app/engines/expertise.py's ``_percentile``."""
    stage_row = db.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == stage_name
        )
    )
    status = stage_row.status if stage_row is not None else StageStatus.pending
    if status in (StageStatus.done, StageStatus.skipped, StageStatus.failed):
        return None
    return JSONResponse(status_code=202, content={"stage": stage_name, "status": status.value})


def _bounds(rows: list[Snapshot]) -> TimelineBounds:
    def _mm(values: list[float]) -> TimelineMetricBounds:
        if not values:
            return TimelineMetricBounds(min=0.0, max=0.0)
        return TimelineMetricBounds(min=float(min(values)), max=float(max(values)))

    hotspot_values = [
        float(h["churn_to_date"])
        for r in rows
        for h in (r.metrics.get("churn_ranked_hotspots") or [])
    ]
    return TimelineBounds(
        file_count=_mm([float(r.metrics["file_count"]) for r in rows]),
        churn_to_date=_mm([float(r.metrics["churn_to_date"]) for r in rows]),
        commits_to_date=_mm([float(r.metrics["commits_to_date"]) for r in rows]),
        active_contributors=_mm([float(r.metrics["active_contributors"]) for r in rows]),
        coupling_pairs_count=_mm([float(r.metrics["coupling_pairs_count"]) for r in rows]),
        hotspot_churn=_mm(hotspot_values),
    )


@router.get("/repos/{repo_id}/timeline", response_model=TimelineResponse)
def get_timeline(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> TimelineResponse | JSONResponse:
    """Gates on "onboarding" -- TimelineEngine runs inside that stage
    (app/jobs/stages.py). Standard ``?run_id=``/``?share=`` contract via
    ``require_repo_access``."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "onboarding", db)
    if pending is not None:
        return pending

    rows = db.scalars(
        select(Snapshot)
        .where(Snapshot.analysis_run_id == resolved_run_id)
        .order_by(Snapshot.position)
    ).all()

    snapshots = [
        TimelineSnapshotOut(
            position=r.position,
            commit_sha=r.commit_sha,
            at_date=r.at_date.isoformat(),
            commit_index=r.commit_index,
            file_count=r.metrics["file_count"],
            churn_to_date=r.metrics["churn_to_date"],
            commits_to_date=r.metrics["commits_to_date"],
            active_contributors=r.metrics["active_contributors"],
            contributor_shares=[
                TimelineContributorShareOut(**c) for c in r.metrics.get("contributor_shares", [])
            ],
            coupling_pairs_count=r.metrics["coupling_pairs_count"],
            top_coupling_pairs=[
                TimelineCouplingPairOut(**p) for p in r.metrics.get("top_coupling_pairs", [])
            ],
            churn_ranked_hotspots=[
                TimelineHotspotOut(**h) for h in r.metrics.get("churn_ranked_hotspots", [])
            ],
        )
        for r in rows
    ]

    return TimelineResponse(
        repo_id=repo_id,
        snapshots=snapshots,
        bounds=_bounds(list(rows)),
        resolution=TimelineResolution(history=len(rows)),
        covers=TIMELINE_COVERS,
        not_covered=TIMELINE_NOT_COVERED,
    )


__all__ = ["router"]
