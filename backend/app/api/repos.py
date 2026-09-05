import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.limits import check_analysis_rate_limit, check_concurrency_cap, check_user_repo_cap
from app.auth.crypto import decrypt_token
from app.auth.deps import (
    current_user_optional,
    current_user_required,
    has_repo_scope,
    require_repo_access,
)
from app.config import settings
from app.db.base import get_db
from app.db.models import (
    AnalysisRun,
    AnalysisStage,
    File,
    Health,
    Job,
    JobStatus,
    Repo,
    RepoStatus,
    Subsystem,
    TruckFactor,
    User,
)
from app.db.runs import get_latest_run
from app.ingestion.guardrails import (
    RepoAccessRequired,
    check_github_repo_size,
    check_github_repo_visibility,
    validate_repo_url,
)
from app.jobs.dispatch import dispatch_run
from app.schemas.repo import (
    AnalysisRunOut,
    AnalysisRunsResponse,
    RepoCreate,
    RepoCreateResponse,
    RepoOut,
    RepoStatusResponse,
    ShowcaseRepoOut,
    ShowcaseReposResponse,
    StageOut,
)

router = APIRouter()


def _showcase_hook(commit_count: int, subsystem_count: int, truck_factor: int | None) -> str:
    parts = [f"{commit_count:,} commits"]
    if subsystem_count:
        parts.append(f"{subsystem_count} subsystem{'s' if subsystem_count != 1 else ''}")
    if truck_factor is not None:
        parts.append(f"truck factor {truck_factor}")
    return " · ".join(parts)


def _parse_owner_name(url: str) -> tuple[str, str]:
    path = urlparse(url).path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Repo URL must include an owner and a repo name.")
    return parts[0], parts[1]


@router.post("/repos", response_model=RepoCreateResponse, status_code=201)
def create_repo(
    payload: RepoCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
) -> RepoCreateResponse:
    # Abuse caps (Part F) gate the whole endpoint, before any GitHub API
    # call or DB write -- a rejected submission here must not itself count
    # against the GitHub API rate limits check_github_repo_size/
    # check_github_repo_visibility would otherwise spend.
    check_analysis_rate_limit(request, user)
    check_concurrency_cap(db)

    try:
        validate_repo_url(payload.url)
        owner, name = _parse_owner_name(payload.url)
        host = urlparse(payload.url).hostname
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    is_private = False
    if host == "github.com":
        token = None
        if user is not None and user.access_token_encrypted is not None and has_repo_scope(user):
            token = decrypt_token(user.access_token_encrypted)

        try:
            is_private = check_github_repo_visibility(owner, name, token)
        except RepoAccessRequired as exc:
            raise HTTPException(
                status_code=403,
                detail=(
                    "This repository may be private. Connect private repositories to " "analyze it."
                ),
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            check_github_repo_size(
                owner,
                name,
                settings.COMPASS_MAX_REPO_MB,
                token=token,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(UTC)
    repo = db.scalar(select(Repo).where(Repo.url == payload.url))
    if repo is None:
        # Session 16, Part C: only a genuinely NEW repo row counts against
        # the per-user cap -- re-analysing something already owned (the
        # `else` branch below) never does, since it doesn't add one.
        if user is not None:
            check_user_repo_cap(user, db)
        repo = Repo(
            url=payload.url,
            owner=owner,
            name=name,
            status=RepoStatus.pending,
            is_private=is_private,
            owner_user_id=user.id if user is not None else None,
            visibility_checked_at=now,
        )
        db.add(repo)
    else:
        # Re-ingestion: reuse the existing repo_id, run_ingestion_job's
        # wipe-then-reinsert makes this a clean full replace, not a
        # duplicate. is_private/visibility_checked_at are refreshed from
        # THIS submission's live check every time (a repo's visibility can
        # change on GitHub). owner_user_id tracks the most recently
        # authenticated submitter -- re-analysis by an anonymous request
        # leaves an existing owner_user_id untouched (an anonymous request
        # can only even reach this point for an already-public repo, since
        # a private one would have 403'd above), but re-analysis by a
        # DIFFERENT authenticated user who also has real GitHub access
        # (proven by check_github_repo_visibility's authenticated retry
        # succeeding) moves ownership to them -- ownership tracks current
        # verified access rather than freezing on whoever happened to
        # submit first, which would otherwise leave a repo permanently
        # owned by a user whose GitHub access was later revoked.
        repo.status = RepoStatus.pending
        repo.is_private = is_private
        repo.visibility_checked_at = now
        if user is not None:
            repo.owner_user_id = user.id
    db.flush()

    job = Job(repo_id=repo.id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db.add(job)
    db.commit()
    db.refresh(repo)
    db.refresh(job)

    dispatch_run(
        repo.id, job.id, db, background_tasks, triggered_by_user_id=user.id if user else None
    )

    return RepoCreateResponse(repo_id=repo.id, job_id=job.id)


@router.get("/repos/showcase", response_model=ShowcaseReposResponse)
def list_showcase_repos(db: Session = Depends(get_db)) -> ShowcaseReposResponse:
    """Session 16, Part A: the home page's showcase cards. Deliberately
    public with no ``require_repo_access`` -- this listing isn't scoped to
    one repo at all (every showcase repo it lists is unconditionally
    readable by anyone regardless, per that dependency's own showcase
    exception), and it must render for an anonymous visitor, which is the
    entire point of a showcase.

    Registered BEFORE ``GET /repos/{repo_id}`` below so the literal path
    ``/repos/showcase`` is matched first -- FastAPI/Starlette resolves
    routes in registration order, and the ``{repo_id}: uuid.UUID`` route
    would otherwise catch this path first and 422 trying to parse the
    literal string "showcase" as a UUID.
    """
    rows = db.scalars(
        select(Repo)
        .where(Repo.is_showcase.is_(True))
        .order_by(Repo.showcase_rank.asc().nulls_last(), Repo.created_at.asc())
    ).all()

    out: list[ShowcaseRepoOut] = []
    for repo in rows:
        subsystem_count = 0
        truck_factor_value: int | None = None
        health_score: float | None = None
        if repo.current_run_id is not None:
            subsystem_count = (
                db.scalar(
                    select(func.count())
                    .select_from(Subsystem)
                    .where(Subsystem.analysis_run_id == repo.current_run_id)
                )
                or 0
            )
            truck_factor_value = db.scalar(
                select(TruckFactor.value).where(TruckFactor.analysis_run_id == repo.current_run_id)
            )
            health_score = db.scalar(
                select(Health.score).where(Health.analysis_run_id == repo.current_run_id)
            )
        out.append(
            ShowcaseRepoOut(
                id=repo.id,
                owner=repo.owner,
                name=repo.name,
                url=repo.url,
                showcase_rank=repo.showcase_rank,
                hook=_showcase_hook(repo.commit_count, subsystem_count, truck_factor_value),
                commit_count=repo.commit_count,
                subsystem_count=subsystem_count,
                truck_factor=truck_factor_value,
                health_score=health_score,
            )
        )
    return ShowcaseReposResponse(repos=out)


def _build_repo_out(repo: Repo, db: Session) -> RepoOut:
    file_count = (
        db.scalar(select(func.count()).select_from(File).where(File.repo_id == repo.id)) or 0
    )

    return RepoOut(
        id=repo.id,
        url=repo.url,
        owner=repo.owner,
        name=repo.name,
        default_branch=repo.default_branch,
        status=repo.status,
        commit_count=repo.commit_count,
        analyzed_at=repo.analyzed_at,
        created_at=repo.created_at,
        file_count=file_count,
        is_private=repo.is_private,
        is_showcase=repo.is_showcase,
        is_claimable=repo.owner_user_id is None and not repo.is_private and not repo.is_showcase,
    )


@router.get("/repos/{repo_id}", response_model=RepoOut)
def get_repo(
    repo_id: uuid.UUID, db: Session = Depends(get_db), repo: Repo = Depends(require_repo_access)
) -> RepoOut:
    return _build_repo_out(repo, db)


@router.post("/repos/{repo_id}/claim", response_model=RepoOut)
def claim_repo(
    repo_id: uuid.UUID,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
    user: User = Depends(current_user_required),
) -> RepoOut:
    """Links a repository with no owner yet (e.g. submitted anonymously) to
    the caller's account, so it starts appearing on their ``GET /me/repos``
    dashboard -- without re-running analysis and without needing to prove
    live GitHub access the way an authenticated ``POST /repos`` resubmission
    already implicitly does (see that endpoint's own ownership comment).

    Deliberately narrower than resubmission's ownership-transfer behaviour:
    this only ever moves a repo from NO owner to the caller -- it can never
    take ownership away from a different account that already claimed or
    submitted it (409), which resubmission-based transfer still can (a
    documented, pre-existing judgement call, unchanged here). Private repos
    are excluded too: one always already has an owner by construction (an
    anonymous submitter can never even create a private repo's row, since
    ``POST /repos``'s visibility check 403s first), so there's nothing to
    claim there. Showcase repos are never claimable, same as they're never
    deletable.
    """
    if repo.is_showcase:
        raise HTTPException(status_code=403, detail="Showcase repositories cannot be claimed.")
    if repo.is_private:
        raise HTTPException(status_code=400, detail="This repository already has an owner.")
    if repo.owner_user_id is not None and repo.owner_user_id != user.id:
        raise HTTPException(
            status_code=409, detail="This repository is already linked to another account."
        )

    if repo.owner_user_id is None:
        repo.owner_user_id = user.id
        db.commit()
        db.refresh(repo)
    return _build_repo_out(repo, db)


@router.get("/repos/{repo_id}/status", response_model=RepoStatusResponse)
def get_repo_status(
    repo_id: uuid.UUID, db: Session = Depends(get_db), repo: Repo = Depends(require_repo_access)
) -> RepoStatusResponse:
    """The single endpoint the frontend polls for progressive reveal (Part
    E, Phase 02): repo status, the LATEST run for this repo (which may still
    be running, or may have just failed -- not necessarily
    ``repo.current_run_id``, which only ever points at the last run that
    reached "ready"), and every stage's status/summary for that run.
    Deliberately cheap: one row lookup for the repo, one for the latest run,
    one query on ``analysis_stages`` -- no joins into any result table.
    """
    latest_run = get_latest_run(repo_id, db)

    stages: list[StageOut] = []
    if latest_run is not None:
        stage_rows = db.scalars(
            select(AnalysisStage)
            .where(AnalysisStage.run_id == latest_run.id)
            .order_by(AnalysisStage.id)
        ).all()
        stages = [
            StageOut(
                name=s.name,
                status=s.status,
                started_at=s.started_at,
                finished_at=s.finished_at,
                error=s.error,
                summary=s.summary,
            )
            for s in stage_rows
        ]

    return RepoStatusResponse(
        repo_id=repo_id,
        repo_status=repo.status,
        current_run_id=repo.current_run_id,
        run_id=latest_run.id if latest_run is not None else None,
        run_status=latest_run.status if latest_run is not None else None,
        run_error=latest_run.error if latest_run is not None else None,
        stages=stages,
        facts_archived=repo.facts_evicted_at is not None,
    )


@router.get("/repos/{repo_id}/runs", response_model=AnalysisRunsResponse)
def get_repo_runs(
    repo_id: uuid.UUID, db: Session = Depends(get_db), _repo: Repo = Depends(require_repo_access)
) -> AnalysisRunsResponse:
    """Every past analysis run for this repo, newest first. Not consumed by
    the frontend yet -- Phase 17's A/B compare will pick a pair of these --
    but exposed now per the Phase 02 spec."""
    rows = db.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.repo_id == repo_id)
        .order_by(AnalysisRun.started_at.desc())
    ).all()

    return AnalysisRunsResponse(
        repo_id=repo_id,
        runs=[
            AnalysisRunOut(
                id=r.id,
                status=r.status,
                head_sha=r.head_sha,
                engine_version=r.engine_version,
                started_at=r.started_at,
                finished_at=r.finished_at,
            )
            for r in rows
        ],
    )


@router.delete("/repos/{repo_id}")
def delete_repo(
    repo_id: uuid.UUID,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
    user: User = Depends(current_user_required),
) -> dict[str, str]:
    """Session 16, Part C: the "clear UI for choosing which" a user already
    at ``MAX_REPOS_PER_USER`` frees a slot with (``DashboardPage``). Owner-
    only, checked explicitly here -- ``require_repo_access`` alone isn't
    enough: it grants a PUBLIC repo to anyone at all, so without this extra
    check any logged-in user could delete someone else's public repository
    (the same "layer an extra check on top of require_repo_access" pattern
    ``app/auth/deps.py::secret_findings_visible`` already established for a
    different endpoint). Deleting the ``repos`` row cascades (``ON DELETE
    CASCADE``) through every Facts and Insight table that references it --
    which is all of them -- so this is a complete, real removal, not a soft
    delete.

    Returns a small JSON body (200), deliberately NOT a bare 204 -- the
    frontend's ``apiDelete`` helper (``frontend/src/api/client.ts``) always
    calls ``res.json()``, the same convention ``DELETE /runs/{id}/share``
    (``app/api/share.py``) already established for exactly this reason.
    """
    if repo.owner_user_id is None or repo.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner may remove this repository.")
    if repo.is_showcase:
        raise HTTPException(status_code=403, detail="Showcase repositories cannot be removed.")
    db.delete(repo)
    db.commit()
    return {"status": "deleted"}
