"""Portfolio endpoints (session 14, Part A/B): ``POST /portfolio/analyze``,
``GET /portfolio/queue``, ``GET /portfolio``.

None of these are ``/repos/{`` shaped routes, so (like ``/compare/runs`` and
``/runs/{run_id}/share``) they're deliberately outside
``test_access_control.py``'s enumeration sweep -- their access rule isn't
"can this request read this one repo", it's simply "the caller is
authenticated", enforced via ``current_user_required`` (a portfolio is
always the CALLER's own data, never another user's; see
``test_portfolio.py``'s dedicated access-control test).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.portfolio import get_or_compute_portfolio
from app.auth.crypto import decrypt_token
from app.auth.deps import current_user_required, has_repo_scope
from app.config import settings
from app.db.base import get_db
from app.db.models import AnalysisRun, AnalysisRunStatus, Repo, RepoStatus, User
from app.ingestion.clone_url import resolve_clone_url
from app.ingestion.cloner import get_remote_head_sha
from app.ingestion.guardrails import (
    RepoAccessRequired,
    check_github_repo_size,
    check_github_repo_visibility,
    validate_repo_url,
)
from app.jobs.queue import create_queued_run, estimate_wait_seconds, queue_position
from app.schemas.portfolio import (
    PortfolioAnalyzeRequest,
    PortfolioAnalyzeResponse,
    PortfolioQueuedItemOut,
    PortfolioQueueResponse,
    PortfolioResponse,
    PortfolioSkippedItemOut,
    PortfolioTotalsOut,
    QueueItemOut,
)

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_PORTFOLIO_BATCH = 50


def _parse_owner_name(url: str) -> tuple[str, str]:
    path = urlparse(url).path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Repo URL must include an owner and a repo name.")
    return parts[0], parts[1]


def _resolve_or_create_repo(url: str, user: User, db: Session) -> Repo:
    """Find-or-create a ``repos`` row for one portfolio URL, applying the
    SAME safety checks ``POST /repos`` applies (SSRF guardrails, GitHub
    visibility/size) -- deliberately re-implemented here rather than
    imported from ``app/api/repos.py::create_repo``, since that function is
    a single FastAPI route handler intertwined with the rate-limit/
    concurrency-cap checks and the dispatch call that only make sense for a
    single, immediately-dispatched submission; extracting a shared helper
    from it was judged riskier (session 14, RULES.md sec 2.5) than a small
    amount of duplication for this batch path, which queues rather than
    dispatches.
    """
    validate_repo_url(url)
    owner, name = _parse_owner_name(url)
    host = urlparse(url).hostname

    is_private = False
    if host == "github.com":
        token = None
        if user.access_token_encrypted is not None and has_repo_scope(user):
            token = decrypt_token(user.access_token_encrypted)
        try:
            is_private = check_github_repo_visibility(owner, name, token)
        except RepoAccessRequired as exc:
            raise ValueError(
                "This repository may be private. Connect private repositories to analyze it."
            ) from exc
        check_github_repo_size(owner, name, settings.COMPASS_MAX_REPO_MB, token=token)

    repo = db.scalar(select(Repo).where(Repo.url == url))
    if repo is None:
        repo = Repo(
            url=url,
            owner=owner,
            name=name,
            status=RepoStatus.pending,
            is_private=is_private,
            owner_user_id=user.id,
        )
        db.add(repo)
        db.flush()
    else:
        repo.is_private = is_private
        if repo.owner_user_id is None:
            repo.owner_user_id = user.id

    return repo


def _already_up_to_date(repo: Repo, db: Session) -> bool:
    """True when ``repo`` already has a ``ready`` current run at the
    repository's CURRENT remote head_sha -- re-analysing it would be pure
    waste (Part A). Only checked for a repo that has actually finished at
    least one analysis before; a brand-new repo, or one that only ever
    failed, is never skipped."""
    if repo.status != RepoStatus.ready or repo.current_run_id is None or not repo.head_sha:
        return False
    try:
        clone_url = resolve_clone_url(repo, db)
        remote_head_sha = get_remote_head_sha(clone_url)
    except (
        Exception
    ) as exc:  # network/git failure -- don't skip, let it queue and fail loudly there
        logger.warning("portfolio: head_sha check failed for %s: %r", repo.url, exc)
        return False
    return remote_head_sha == repo.head_sha


@router.post("/portfolio/analyze", response_model=PortfolioAnalyzeResponse)
def post_portfolio_analyze(
    payload: PortfolioAnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user_required),
) -> PortfolioAnalyzeResponse:
    if len(payload.repository_urls) > MAX_PORTFOLIO_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_PORTFOLIO_BATCH} repository URLs per submission.",
        )

    queued: list[PortfolioQueuedItemOut] = []
    skipped: list[PortfolioSkippedItemOut] = []
    errors: list[PortfolioSkippedItemOut] = []

    for url in payload.repository_urls:
        try:
            repo = _resolve_or_create_repo(url, user, db)
        except ValueError as exc:
            errors.append(PortfolioSkippedItemOut(url=url, reason=str(exc)))
            continue

        if _already_up_to_date(repo, db):
            skipped.append(
                PortfolioSkippedItemOut(
                    url=url, reason="Already analyzed at the current head commit."
                )
            )
            continue

        run, _job = create_queued_run(repo.id, db, triggered_by_user_id=user.id)
        queued.append(PortfolioQueuedItemOut(repo_id=repo.id, run_id=run.id, url=url))

    db.commit()
    return PortfolioAnalyzeResponse(queued=queued, skipped=skipped, errors=errors)


@router.get("/portfolio/queue", response_model=PortfolioQueueResponse)
def get_portfolio_queue(
    db: Session = Depends(get_db), user: User = Depends(current_user_required)
) -> PortfolioQueueResponse:
    runs = db.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.triggered_by_user_id == user.id,
            AnalysisRun.status.in_((AnalysisRunStatus.queued, AnalysisRunStatus.running)),
        )
        .order_by(AnalysisRun.queued_at.asc().nulls_last(), AnalysisRun.started_at.asc())
    ).all()

    items: list[QueueItemOut] = []
    for run in runs:
        repo = db.get(Repo, run.repo_id)
        if repo is None:
            continue
        if run.status == AnalysisRunStatus.queued:
            position = queue_position(run.id, db)
            wait = estimate_wait_seconds(position, db) if position is not None else None
        else:
            position = None
            wait = None
        items.append(
            QueueItemOut(
                run_id=run.id,
                repo_id=repo.id,
                repo_url=repo.url,
                status=run.status.value,
                position=position,
                estimated_wait_seconds=wait,
            )
        )

    return PortfolioQueueResponse(
        items=items, max_concurrent_runs=settings.COMPASS_MAX_CONCURRENT_RUNS
    )


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(
    db: Session = Depends(get_db), user: User = Depends(current_user_required)
) -> PortfolioResponse:
    data, computed_at = get_or_compute_portfolio(db, user.id)
    db.commit()
    return PortfolioResponse(
        computed_at=computed_at,
        repository_count=data["repository_count"],
        totals=PortfolioTotalsOut(**data["totals"]),
        language_activity_by_year=data["language_activity_by_year"],
        pooled_distributions=data["pooled_distributions"],
        cross_repo_patterns=data["cross_repo_patterns"],
        portfolio_health=data["portfolio_health"],
        growth=data["growth"],
    )


__all__ = ["router"]
