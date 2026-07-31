import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import AnalysisRun, AnalysisStage, File, Job, JobStatus, Repo, RepoStatus
from app.db.runs import get_latest_run
from app.ingestion.guardrails import validate_repo_url
from app.jobs.runner import run_ingestion_job
from app.schemas.repo import (
    AnalysisRunOut,
    AnalysisRunsResponse,
    RepoCreate,
    RepoCreateResponse,
    RepoOut,
    RepoStatusResponse,
    StageOut,
)

router = APIRouter()


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
    payload: RepoCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> RepoCreateResponse:
    try:
        validate_repo_url(payload.url)
        owner, name = _parse_owner_name(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo = db.scalar(select(Repo).where(Repo.url == payload.url))
    if repo is None:
        repo = Repo(url=payload.url, owner=owner, name=name, status=RepoStatus.pending)
        db.add(repo)
    else:
        # Re-ingestion: reuse the existing repo_id, run_ingestion_job's
        # wipe-then-reinsert makes this a clean full replace, not a duplicate.
        repo.status = RepoStatus.pending
    db.flush()

    job = Job(repo_id=repo.id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db.add(job)
    db.commit()
    db.refresh(repo)
    db.refresh(job)

    background_tasks.add_task(run_ingestion_job, repo.id, job.id)

    return RepoCreateResponse(repo_id=repo.id, job_id=job.id)


@router.get("/repos/{repo_id}", response_model=RepoOut)
def get_repo(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> RepoOut:
    repo = db.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repo not found.")

    file_count = (
        db.scalar(select(func.count()).select_from(File).where(File.repo_id == repo_id)) or 0
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
    )


@router.get("/repos/{repo_id}/status", response_model=RepoStatusResponse)
def get_repo_status(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> RepoStatusResponse:
    """The single endpoint the frontend polls for progressive reveal (Part
    E, Phase 02): repo status, the LATEST run for this repo (which may still
    be running, or may have just failed -- not necessarily
    ``repo.current_run_id``, which only ever points at the last run that
    reached "ready"), and every stage's status/summary for that run.
    Deliberately cheap: one row lookup for the repo, one for the latest run,
    one query on ``analysis_stages`` -- no joins into any result table.
    """
    repo = db.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repo not found.")

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
    )


@router.get("/repos/{repo_id}/runs", response_model=AnalysisRunsResponse)
def get_repo_runs(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> AnalysisRunsResponse:
    """Every past analysis run for this repo, newest first. Not consumed by
    the frontend yet -- Phase 17's A/B compare will pick a pair of these --
    but exposed now per the Phase 02 spec."""
    if db.get(Repo, repo_id) is None:
        raise HTTPException(status_code=404, detail="Repo not found.")

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
