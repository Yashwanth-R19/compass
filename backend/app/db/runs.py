import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Repo


def get_latest_run(repo_id: uuid.UUID, session: Session) -> AnalysisRun | None:
    """Most recent ``analysis_runs`` row for a repo by ``started_at``,
    regardless of status -- what ``GET /repos/{id}/status`` polls, since a
    run that's still in progress (or one that just failed) hasn't been
    promoted to ``repos.current_run_id`` yet, and the frontend needs to see
    its stage list update live either way."""
    return session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.repo_id == repo_id)
        .order_by(AnalysisRun.started_at.desc())
        .limit(1)
    )


def resolve_run_id(
    repo: Repo, explicit_run_id: uuid.UUID | None, session: Session
) -> uuid.UUID | None:
    """The run a result-reading endpoint (coupling/architecture/risk/
    health/findings) should query, per Part E's ``?run_id=`` contract.

    An explicit ``?run_id=`` always wins. Otherwise prefers
    ``repo.current_run_id`` (the last run that reached "ready"), but falls
    back to the latest run for the repo when ``current_run_id`` is still
    NULL. That fallback is not cosmetic: ``current_run_id`` is only set once
    a run finishes, so without it, progressive reveal could never work
    during a repo's FIRST-ever analysis -- every result endpoint would have
    no run to resolve to until the whole run was already done, defeating
    the point of this phase.

    Returns ``None`` only when there is truly no run yet to resolve to (a
    brand new repo whose ingestion job hasn't created its first
    ``analysis_runs`` row).
    """
    if explicit_run_id is not None:
        return explicit_run_id
    if repo.current_run_id is not None:
        return repo.current_run_id
    latest = get_latest_run(repo.id, session)
    return latest.id if latest is not None else None
