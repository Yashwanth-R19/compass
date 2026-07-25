import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import File, Job, JobStatus, Repo, RepoStatus
from app.ingestion.guardrails import validate_repo_url
from app.jobs.runner import run_ingestion_job
from app.schemas.repo import RepoCreate, RepoCreateResponse, RepoOut

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

    file_count = db.scalar(select(func.count()).select_from(File).where(File.repo_id == repo_id)) or 0

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
