"""``GET /compare/runs?a=<run_id>&b=<run_id>`` (session 13, Part E).

Not a ``/repos/{`` shaped route -- it takes two run ids directly, so it is
deliberately outside ``test_access_control.py``'s ``/repos/{``-enumeration
sweep, the same precedent ``app/api/share.py`` already set for
``/runs/{run_id}/share``/``/shared/{slug}``. Its own access rule -- the
request must be authorized to read BOTH runs' repos independently -- is a
different check than "can this request read this one repo", enforced inline
here rather than by reusing ``require_repo_access`` (which only ever checks
one repo per call).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.analysis.compare import compare_runs
from app.auth.deps import current_user_optional
from app.db.base import get_db
from app.db.models import AnalysisRun, Repo, User
from app.schemas.compare import CompareResponse

router = APIRouter()


def _readable_run(run_id: uuid.UUID, user: User | None, db: Session) -> AnalysisRun:
    """The same public/owner-only rule ``require_repo_access`` applies to a
    ``repo_id`` path param, applied directly to a run instead. Deliberately
    does NOT accept a ``?share=`` slug: a share link grants access to one run
    for viewing THAT run's own analysis pages (CLAUDE.md), not for pairing it
    into an arbitrary compare against a second run of the caller's own
    choosing -- accepting one here would let a share-link holder read a
    second run's data the link was never issued for."""
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    repo = db.get(Repo, run.repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    if not repo.is_private:
        return run
    if user is not None and repo.owner_user_id is not None and user.id == repo.owner_user_id:
        return run
    raise HTTPException(
        status_code=403,
        detail="This repository is private. Connect private repositories to view it.",
    )


@router.get("/compare/runs", response_model=CompareResponse)
def get_compare(
    a: uuid.UUID,
    b: uuid.UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
) -> CompareResponse:
    """Requires access to BOTH runs, checked independently (Known Hazard #7:
    "it is easy to check the requesting user can read run A and forget run
    B") -- a user must never be able to diff a repository they can read
    against a private one they cannot, which would leak the private side's
    metrics through the comparison."""
    run_a = _readable_run(a, user, db)
    run_b = _readable_run(b, user, db)

    if run_a.repo_id != run_b.repo_id:
        raise HTTPException(status_code=400, detail="Both runs must belong to the same repository.")

    return compare_runs(db, run_a, run_b)


__all__ = ["router"]
