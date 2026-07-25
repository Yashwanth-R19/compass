import os
import shutil
import stat
import uuid
from datetime import datetime, timezone

from app.db.base import SessionLocal
from app.db.models import Job, JobStatus, Repo, RepoStatus
from app.ingestion.cloner import clone_repo
from app.ingestion.miner import mine_repo
from app.ingestion.persist import persist_mined_repo


def run_ingestion_job(repo_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Clone -> mine -> persist a repo, tracking progress on the job row.

    Transport-agnostic by design: called from FastAPI BackgroundTasks today,
    but takes no FastAPI objects and can be invoked identically from a future
    GitHub Actions worker. Always cleans up the clone, success or failure.
    """
    session = SessionLocal()
    clone_path: str | None = None
    try:
        _update_job(session, job_id, status=JobStatus.running, progress=0)
        _update_repo(session, repo_id, status=RepoStatus.mining)
        session.commit()

        repo = session.get(Repo, repo_id)
        clone_path = clone_repo(repo.url)
        _update_job(session, job_id, progress=20)
        session.commit()

        mined = mine_repo(clone_path)
        _update_job(session, job_id, progress=60)
        session.commit()

        persist_mined_repo(repo_id, mined, session)
        _update_repo(
            session,
            repo_id,
            status=RepoStatus.ready,
            commit_count=len(mined.commits),
            analyzed_at=datetime.now(timezone.utc),
        )
        _update_job(session, job_id, progress=90)
        session.commit()

        _update_job(
            session, job_id, status=JobStatus.done, progress=100, finished_at=datetime.now(timezone.utc)
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        _update_job(
            session,
            job_id,
            status=JobStatus.failed,
            error=str(exc),
            finished_at=datetime.now(timezone.utc),
        )
        _update_repo(session, repo_id, status=RepoStatus.failed)
        session.commit()
        raise
    finally:
        if clone_path is not None:
            _rmtree_force(clone_path)
        session.close()


def _rmtree_force(path: str) -> None:
    """shutil.rmtree that survives git's read-only files on Windows.

    Git marks some clone internals (packed-refs, .idx files) read-only; a
    plain rmtree(ignore_errors=True) silently leaves them behind instead of
    raising, so the clone never actually gets deleted. Clearing the read-only
    bit on failure and retrying once is the standard workaround.
    """

    def _on_error(func, target, exc_info):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=_on_error)


def _update_job(session, job_id: uuid.UUID, **fields) -> None:
    job = session.get(Job, job_id)
    for key, value in fields.items():
        setattr(job, key, value)


def _update_repo(session, repo_id: uuid.UUID, **fields) -> None:
    repo = session.get(Repo, repo_id)
    for key, value in fields.items():
        setattr(repo, key, value)
