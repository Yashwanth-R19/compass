import os
import shutil
import stat
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.db.models import AnalysisRun, AnalysisRunStatus, File, Job, JobStatus, Repo, RepoStatus
from app.ingestion.cloner import clone_repo, get_remote_head_sha
from app.ingestion.miner import mine_repo
from app.ingestion.persist import persist_facts
from app.jobs.stages import (
    FACT_STAGES,
    INSIGHT_STAGES,
    create_pending_stages,
    mark_stage_skipped,
    stage,
)
from app.languages.scanner import extract_structural_edges


def run_ingestion_job(repo_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Create a new ``analysis_runs`` row and drive it through the FACT
    stages (clone -> mine -> structure -> persist_facts, skipped entirely if
    the remote head_sha is unchanged) and then the INSIGHT stages (coupling
    -> architecture -> overlay -> risk -> health -> rank), tracking progress
    on both the legacy ``jobs`` row and the new per-stage ``analysis_stages``
    rows throughout (Phase 02: Facts/Insight split + progressive reveal,
    CLAUDE.md).

    Transport-agnostic by design: called from FastAPI BackgroundTasks today,
    but takes no FastAPI objects and can be invoked identically from a future
    GitHub Actions worker. Always cleans up the clone, success or failure.

    On success: the run is marked ``ready``, ``repos.current_run_id``/
    ``head_sha`` move to point at it, and the previously-current run (if any)
    is marked ``superseded`` -- it keeps its rows, nothing about it is
    deleted. On failure: the run and its failing stage are marked ``failed``
    (by ``app.jobs.stages.stage()``, which commits before re-raising), the
    ``jobs``/``repos`` rows are marked failed here, and CRUCIALLY
    ``repos.current_run_id``/``head_sha`` are left untouched -- a failed
    re-analysis must never blank out a repo that already had a good run.
    """
    session = SessionLocal()
    clone_path: str | None = None
    run_id: uuid.UUID | None = None
    try:
        _update_job(session, job_id, status=JobStatus.running, progress=0)
        session.commit()

        repo_url = session.scalar(select(Repo.url).where(Repo.id == repo_id))
        previous_head_sha = session.scalar(select(Repo.head_sha).where(Repo.id == repo_id))
        previous_run_id = session.scalar(select(Repo.current_run_id).where(Repo.id == repo_id))

        # head_sha is filled in once resolved below; the run/stage rows are
        # created and committed FIRST, before the (network-dependent)
        # `git ls-remote` call, so a slow-to-respond remote never delays the
        # first status poll from seeing the full pending stage list -- the
        # "land on the repo page within ~2 seconds" requirement (Part F).
        run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.running, head_sha="")
        session.add(run)
        session.flush()
        run_id = run.id
        create_pending_stages(run_id, session)
        session.commit()
        _update_job(session, job_id, progress=5)
        session.commit()

        remote_head_sha = get_remote_head_sha(repo_url)
        run.head_sha = remote_head_sha

        facts_exist = bool(
            session.scalar(select(func.count()).select_from(File).where(File.repo_id == repo_id))
        )
        # This is what makes re-analysing an unchanged repo nearly instant: a
        # real feature, not just an optimization -- the four FACT stages are
        # skipped entirely and the run jumps straight to Insight.
        reuse_facts = (
            previous_head_sha is not None and previous_head_sha == remote_head_sha and facts_exist
        )

        if reuse_facts:
            for s in FACT_STAGES:
                mark_stage_skipped(
                    run_id,
                    s.name,
                    session,
                    {"reason": f"head_sha {remote_head_sha[:8]} unchanged; facts reused"},
                )
            commit_count = session.scalar(select(Repo.commit_count).where(Repo.id == repo_id)) or 0
        else:
            _update_repo(session, repo_id, status=RepoStatus.mining)
            session.commit()

            with stage(run_id, "clone", session) as summary:
                clone_path = clone_repo(repo_url)
                summary["cloned"] = True
            _update_job(session, job_id, progress=15)
            session.commit()

            with stage(run_id, "mine", session) as summary:
                mined = mine_repo(clone_path)
                summary["commits"] = len(mined.commits)
                summary["files"] = len(mined.files)
            _update_job(session, job_id, progress=40)
            session.commit()

            with stage(run_id, "structure", session) as summary:
                dependencies = extract_structural_edges(clone_path)
                summary["dependencies"] = len(dependencies)
            _update_job(session, job_id, progress=55)
            session.commit()

            with stage(run_id, "persist_facts", session) as summary:
                persist_facts(repo_id, mined, dependencies, session)
                summary["commits"] = len(mined.commits)
                summary["files"] = len(mined.files)

            # Clone is disposable and no longer needed -- everything from
            # here on is pure DB-only analysis (master-context.md sec 9).
            _rmtree_force(clone_path)
            clone_path = None
            commit_count = len(mined.commits)

            _update_job(session, job_id, progress=70)
            session.commit()

        _update_repo(session, repo_id, status=RepoStatus.analyzing)
        session.commit()

        # Engine order is fixed and load-bearing -- see app/jobs/stages.py's
        # INSIGHT_STAGES docstring for why each depends on the last.
        for s in INSIGHT_STAGES:
            with stage(run_id, s.name, session) as summary:
                assert s.callable is not None  # every insight stage has one
                summary.update(s.callable(repo_id, run_id, session))
            session.commit()
        _update_job(session, job_id, progress=95)
        session.commit()

        run_row = session.get(AnalysisRun, run_id)
        run_row.status = AnalysisRunStatus.ready
        run_row.finished_at = datetime.now(UTC)

        if previous_run_id is not None and previous_run_id != run_id:
            previous_run = session.get(AnalysisRun, previous_run_id)
            if previous_run is not None:
                previous_run.status = AnalysisRunStatus.superseded

        _update_repo(
            session,
            repo_id,
            status=RepoStatus.ready,
            current_run_id=run_id,
            head_sha=remote_head_sha,
            commit_count=commit_count,
            analyzed_at=datetime.now(UTC),
        )
        _update_job(
            session, job_id, status=JobStatus.done, progress=100, finished_at=datetime.now(UTC)
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        # A failure outside any stage() block (e.g. get_remote_head_sha
        # raising before a single stage ran) wouldn't otherwise mark the run
        # failed -- stage() only does that for failures inside its own
        # try/except. Defensive, idempotent if stage() already did it.
        if run_id is not None:
            run_row = session.get(AnalysisRun, run_id)
            if run_row is not None and run_row.status == AnalysisRunStatus.running:
                run_row.status = AnalysisRunStatus.failed
                run_row.error = str(exc)
                run_row.finished_at = datetime.now(UTC)

        _update_job(
            session,
            job_id,
            status=JobStatus.failed,
            error=str(exc),
            finished_at=datetime.now(UTC),
        )
        # CRUCIAL: never touch repo.current_run_id/head_sha here -- a failed
        # re-analysis must leave the repo pointing at its previous good run.
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
