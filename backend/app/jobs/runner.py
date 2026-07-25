import os
import shutil
import stat
import uuid
from datetime import datetime, timezone

from app.db.base import SessionLocal
from app.db.models import Job, JobStatus, Repo, RepoStatus
from app.engines.architecture import ArchEngine
from app.engines.coupling import CouplingEngine
from app.engines.findings import FindingsRankEngine
from app.engines.health import HealthEngine
from app.engines.overlay import OverlayEngine
from app.engines.risk import RiskEngine
from app.ingestion.cloner import clone_repo
from app.ingestion.miner import mine_repo
from app.ingestion.persist import persist_mined_repo
from app.languages.scanner import extract_structural_edges


def run_ingestion_job(repo_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Clone -> mine -> parse structure -> persist -> delete clone -> run
    analysis engines, tracking progress on the job row throughout.

    Transport-agnostic by design: called from FastAPI BackgroundTasks today,
    but takes no FastAPI objects and can be invoked identically from a future
    GitHub Actions worker. Always cleans up the clone, success or failure.

    Structural (import) parsing runs here, while the clone still exists, and
    its edges are persisted alongside the mined commits/files (see
    app/languages/scanner.py). Every analysis engine only ever reads the DB,
    so they all run after the clone is already deleted — this is the one
    pipeline covering both ingestion and analysis (master-context.md sec 9);
    repo.status tracks it as mining -> analyzing -> ready. An engine failure
    fails the whole job/repo, same as a mining failure would.

    Engine order is fixed and load-bearing: Coupling -> Architecture ->
    Overlay (needs both of the previous two) -> Risk (needs Coupling's
    max-coupling-degree per file) -> Health (needs Risk's file_metrics plus
    Architecture's cycles and Overlay's hidden-dependency count) ->
    FindingsRank (needs every other engine's findings already written, to
    compute one global rank across categories).
    """
    session = SessionLocal()
    clone_path: str | None = None
    try:
        _update_job(session, job_id, status=JobStatus.running, progress=0)
        _update_repo(session, repo_id, status=RepoStatus.mining)
        session.commit()

        repo = session.get(Repo, repo_id)
        clone_path = clone_repo(repo.url)
        _update_job(session, job_id, progress=15)
        session.commit()

        mined = mine_repo(clone_path)
        _update_job(session, job_id, progress=40)
        session.commit()

        dependencies = extract_structural_edges(clone_path)
        _update_job(session, job_id, progress=55)
        session.commit()

        persist_mined_repo(repo_id, mined, dependencies, session)
        _update_job(session, job_id, progress=70)
        session.commit()

        # Clone is disposable and no longer needed — everything from here on
        # is pure DB-only analysis (master-context.md sec 9: "the clone is
        # disposable").
        _rmtree_force(clone_path)
        clone_path = None

        _update_repo(session, repo_id, status=RepoStatus.analyzing)
        session.commit()

        CouplingEngine().run(repo_id, session)
        ArchEngine().run(repo_id, session)
        OverlayEngine().run(repo_id, session)
        RiskEngine().run(repo_id, session)
        HealthEngine().run(repo_id, session)
        FindingsRankEngine().run(repo_id, session)
        _update_job(session, job_id, progress=95)
        session.commit()

        _update_repo(
            session,
            repo_id,
            status=RepoStatus.ready,
            commit_count=len(mined.commits),
            analyzed_at=datetime.now(timezone.utc),
        )
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
