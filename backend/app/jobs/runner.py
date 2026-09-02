import os
import shutil
import stat
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    File,
    Job,
    JobStatus,
    Repo,
    RepoStatus,
)
from app.db.paths import load_path_id_map
from app.engines.context import RunContext
from app.ingestion.clone_url import resolve_clone_url
from app.ingestion.cloner import clone_repo, get_remote_head_sha
from app.ingestion.manifests import extract_declared_dependencies, extract_manifests
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
from app.security.scanner import persist_secret_hits, scan_history

SOFT_TIMEOUT_MINUTES = 12
"""Session 16, Part C: an in-worker soft ceiling, comfortably under
``mine.yml``'s own 15-minute ``timeout-minutes`` (which would otherwise
hard-kill the whole process mid-stage, with no chance to fail gracefully)
and under ``app/jobs/reaper.py``'s 20-minute stale-run cutoff (which would
otherwise be the first thing to even notice, and could take up to 20 more
minutes to fire). Checked only BETWEEN stage boundaries, never mid-stage --
each ``with stage(...)`` block already runs to completion and commits
normally once entered (progressive reveal's per-stage-commit design), so
"partial results preserved" needs no extra bookkeeping here: whatever
stages finished before the checkpoint fired stay `done`/queryable exactly as
if the run had completed normally, and `_SoftTimeoutExceeded` is caught by
this function's own outer `except Exception` -- the same path that already
marks the run `failed` (with this exception's message) and, crucially,
never touches `repos.current_run_id`/`head_sha`."""


class _SoftTimeoutExceeded(RuntimeError):
    pass


def _check_soft_timeout(job_started_at: datetime) -> None:
    elapsed = datetime.now(UTC) - job_started_at
    if elapsed > timedelta(minutes=SOFT_TIMEOUT_MINUTES):
        raise _SoftTimeoutExceeded(
            f"Soft timeout: run exceeded {SOFT_TIMEOUT_MINUTES} minutes "
            f"({elapsed.total_seconds():.0f}s elapsed) -- stopped after the last "
            "completed stage so already-computed results stay available."
        )


def run_ingestion_job(
    repo_id: uuid.UUID,
    job_id: uuid.UUID,
    worker_mode: str = "inline",
    triggered_by_user_id: uuid.UUID | None = None,
    existing_analysis_run_id: uuid.UUID | None = None,
) -> None:
    """Create a new ``analysis_runs`` row and drive it through the FACT
    stages (clone -> mine -> structure -> persist_facts -> secrets, skipped
    entirely if the remote head_sha is unchanged) and then the INSIGHT
    stages (coupling -> subsystems -> architecture -> risk -> knowledge ->
    onboarding -> security -> rank, see ``app/jobs/stages.py::INSIGHT_STAGES``
    for the canonical, load-bearing order), tracking progress on both the
    legacy ``jobs`` row and the per-stage ``analysis_stages``
    rows throughout (Phase 02: Facts/Insight split + progressive reveal,
    CLAUDE.md).

    Session 10: the clone is now deleted after the "secrets" FACT stage
    (which needs it for ``git log -p``), not immediately after
    "persist_facts" -- see the restructured body below.

    Transport-agnostic by design: called from FastAPI BackgroundTasks
    (``worker_mode="inline"``/``"inline_fallback"``, app/jobs/dispatch.py) and
    from the GitHub Actions worker (``worker_mode="actions"``,
    app/jobs/worker.py) -- the exact same function either way, no branching
    on transport inside it. ``worker_mode`` exists only because
    ``analysis_runs.worker_mode`` (session 01, Part G) is set on the row this
    function itself creates below, and the caller is the only one who knows
    which transport actually ran it; nothing else about the function's
    behavior depends on it. Always cleans up the clone, success or failure.

    On success: the run is marked ``ready``, ``repos.current_run_id``/
    ``head_sha`` move to point at it, and the previously-current run (if any)
    is marked ``superseded`` -- it keeps its rows, nothing about it is
    deleted. On failure: the run and its failing stage are marked ``failed``
    (by ``app.jobs.stages.stage()``, which commits before re-raising), the
    ``jobs``/``repos`` rows are marked failed here, and CRUCIALLY
    ``repos.current_run_id``/``head_sha`` are left untouched -- a failed
    re-analysis must never blank out a repo that already had a good run.

    ``triggered_by_user_id`` is best-effort audit only (session 02,
    ``analysis_runs.triggered_by_user_id``) -- see that column's docstring
    in app/db/models.py for why it's populated for inline/inline_fallback
    runs but always NULL for "actions"-mode runs.

    ``existing_analysis_run_id`` (session 14) resumes an ``analysis_runs``
    row created AHEAD OF TIME with ``status=queued`` by
    ``app/jobs/queue.py::create_queued_run`` (its ``analysis_stages`` rows
    already pre-created too), instead of creating a brand-new run row --
    this is what lets the run queue's round-robin dispatcher hand off to
    this same transport-agnostic function rather than duplicating any
    pipeline logic. ``None`` (the default) is the pre-session-14 behavior,
    unchanged: create a fresh run row here, as the first step.
    """
    session = SessionLocal()
    clone_path: str | None = None
    run_id: uuid.UUID | None = None
    # Session 16, Part C: measured from when THIS function actually started
    # doing work, not from any DB timestamp -- run.started_at isn't
    # re-stamped when a queued run is dispatched (CLAUDE.md's queue section),
    # so using it here would unfairly count time spent sitting in the queue
    # against the soft timeout.
    job_started_at = datetime.now(UTC)
    try:
        _update_job(session, job_id, status=JobStatus.running, progress=0)
        session.commit()

        repo_row = session.get(Repo, repo_id)
        previous_head_sha = repo_row.head_sha
        previous_run_id = repo_row.current_run_id

        if existing_analysis_run_id is not None:
            run = session.get(AnalysisRun, existing_analysis_run_id)
            if run is None:
                raise RuntimeError(
                    f"existing_analysis_run_id {existing_analysis_run_id} does not exist"
                )
            run.status = AnalysisRunStatus.running
            run.worker_mode = worker_mode
            if triggered_by_user_id is not None:
                run.triggered_by_user_id = triggered_by_user_id
            session.commit()
        else:
            # head_sha is filled in once resolved below; the run/stage rows
            # are created and committed FIRST, before the (network-dependent)
            # `git ls-remote` call, so a slow-to-respond remote never delays
            # the first status poll from seeing the full pending stage list
            # -- the "land on the repo page within ~2 seconds" requirement
            # (Part F).
            run = AnalysisRun(
                repo_id=repo_id,
                status=AnalysisRunStatus.running,
                head_sha="",
                worker_mode=worker_mode,
                triggered_by_user_id=triggered_by_user_id,
            )
            session.add(run)
            session.flush()
            create_pending_stages(run.id, session)
            session.commit()
        run_id = run.id
        _update_job(session, job_id, progress=5)
        session.commit()

        # Resolves to the plain repo.url for a public repo, or an
        # x-access-token-embedded URL for a private one (session 02, Part
        # D) -- resolved once and reused for both the ls-remote check below
        # and the clone stage, so a private repo's owner token is only
        # decrypted once per job.
        clone_url = resolve_clone_url(repo_row, session)

        remote_head_sha = get_remote_head_sha(clone_url)
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
            # Session 10: GET /repos/{id}/vulnerabilities reads
            # "dependency_manifest_found" back from the "structure" stage's
            # own summary (see that endpoint's docstring) -- on a reuse run
            # "structure" is marked skipped with a generic reason instead of
            # actually running extract_declared_dependencies again, so that
            # flag has to be carried forward from the PREVIOUS run's
            # "structure" stage explicitly, or every re-analysis of an
            # unchanged repo would wrongly report "no supported manifest"
            # even when one genuinely exists (dependencies_declared itself
            # is unaffected -- it's Facts, untouched by this skip -- only
            # the stage-summary teaser needs this carry-forward).
            previous_manifest_found: bool | None = None
            if previous_run_id is not None:
                previous_structure_row = session.scalar(
                    select(AnalysisStage).where(
                        AnalysisStage.run_id == previous_run_id,
                        AnalysisStage.name == "structure",
                    )
                )
                if previous_structure_row is not None and previous_structure_row.summary:
                    previous_manifest_found = previous_structure_row.summary.get(
                        "dependency_manifest_found"
                    )

            for s in FACT_STAGES:
                summary: dict = {
                    "reason": f"head_sha {remote_head_sha[:8]} unchanged; facts reused"
                }
                if s.name == "structure" and previous_manifest_found is not None:
                    summary["dependency_manifest_found"] = previous_manifest_found
                mark_stage_skipped(run_id, s.name, session, summary)
            commit_count = session.scalar(select(Repo.commit_count).where(Repo.id == repo_id)) or 0
        else:
            _update_repo(session, repo_id, status=RepoStatus.mining)
            session.commit()

            with stage(run_id, "clone", session) as summary:
                clone_path = clone_repo(clone_url)
                summary["cloned"] = True
            _update_job(session, job_id, progress=15)
            session.commit()
            _check_soft_timeout(job_started_at)

            with stage(run_id, "mine", session) as summary:
                mined = mine_repo(clone_path)
                summary["commits"] = len(mined.commits)
                summary["files"] = len(mined.files)
            _update_job(session, job_id, progress=40)
            session.commit()
            _check_soft_timeout(job_started_at)

            with stage(run_id, "structure", session) as summary:
                scan_result = extract_structural_edges(clone_path)
                dependencies = scan_result.edges
                symbols = scan_result.symbols
                manifests = extract_manifests(clone_path)
                # Session 10, Part C: a SEPARATE pass parsing the same four
                # supported dependency-manifest formats into structured
                # rows for `dependencies_declared` -- see
                # app/ingestion/manifests.py's module docstring for why
                # this isn't folded into `manifests` above.
                declared_dependencies, manifest_found = extract_declared_dependencies(clone_path)
                # "dependencies" kept alongside "edges" (session 03's
                # spec'd key) so RepoLayout's existing structure-stage pill
                # (frontend/src/pages/RepoLayout.tsx::STAGE_SUMMARY_KEY,
                # untouched this session) keeps reading a real count instead
                # of going blank -- summary is a free-form JSONB teaser, not
                # a locked schema, so both keys can coexist.
                summary["dependencies"] = len(dependencies)
                summary["edges"] = len(dependencies)
                summary["symbols"] = len(symbols)
                summary["manifests"] = len(manifests)
                summary["by_language"] = scan_result.by_language
                summary["declared_dependencies"] = len(declared_dependencies)
                # Read back by GET /repos/{id}/vulnerabilities (session 10,
                # Part F) to distinguish "no supported manifest" from
                # "manifest present, genuinely zero vulnerabilities" --
                # same "read a real column/teaser back from a stage's own
                # summary" pattern /subsystems' `modularity` already uses.
                summary["dependency_manifest_found"] = manifest_found
            _update_job(session, job_id, progress=55)
            session.commit()
            _check_soft_timeout(job_started_at)

            with stage(run_id, "persist_facts", session) as summary:
                persist_facts(
                    repo_id, mined, dependencies, symbols, manifests, declared_dependencies, session
                )
                summary["commits"] = len(mined.commits)
                summary["files"] = len(mined.files)
            _check_soft_timeout(job_started_at)

            # Session 10, Part F: "secrets" needs BOTH the clone (for
            # `git log -p`) and interned repo_paths ids (for
            # secret_hits.path_id) -- only persist_facts, just above,
            # produces the second, which is why this FACT stage runs AFTER
            # it rather than alongside "structure"/"mine". The clone
            # therefore has to survive one stage longer than it used to;
            # see the deletion point moved below, out of this stage's body.
            with stage(run_id, "secrets", session) as summary:
                path_id_map = load_path_id_map(repo_id, session)
                scan_result_secrets = scan_history(
                    clone_path, salt=settings.COMPASS_SECRET_SCAN_SALT
                )
                persist_secret_hits(repo_id, scan_result_secrets.hits, path_id_map, session)
                summary["hits_found"] = len(scan_result_secrets.hits)
                summary["still_in_head"] = sum(
                    1 for h in scan_result_secrets.hits if h.still_in_head
                )
                summary["commits_scanned"] = scan_result_secrets.commits_scanned
                summary["truncated"] = scan_result_secrets.truncated
                if scan_result_secrets.truncation_reason:
                    summary["truncation_reason"] = scan_result_secrets.truncation_reason

            # Clone is disposable and no longer needed -- everything from
            # here on is pure DB-only analysis (master-context.md sec 9).
            # Session 10: this now happens AFTER "secrets" (see above), not
            # immediately after persist_facts -- if any FACT stage between
            # here and there raises, the exception propagates past this
            # point with clone_path still set, and the outer try/finally at
            # the bottom of this function deletes it on that failure path
            # too (session 10 Known Hazard #6).
            _rmtree_force(clone_path)
            clone_path = None
            commit_count = len(mined.commits)

            _update_job(session, job_id, progress=70)
            session.commit()
            _check_soft_timeout(job_started_at)

        _update_repo(session, repo_id, status=RepoStatus.analyzing)
        session.commit()

        # One RunContext per run, built once analysis_runs exists and shared
        # across every insight stage -- it's what lets ArchEngine/OverlayEngine/
        # HealthEngine stop re-deriving the same dependency graph/cycles/
        # hidden-dependency list three times per run (session 01). Never
        # constructed before this point and never reused across runs (see
        # app/engines/context.py's docstring).
        ctx = RunContext(repo_id=repo_id, run_id=run_id)

        # Engine order is fixed and load-bearing -- see app/jobs/stages.py's
        # INSIGHT_STAGES docstring for why each depends on the last. A stage
        # may run several engines in sequence (session 04) -- each one's
        # summary dict is merged into the stage's single JSONB summary, in
        # the SAME order app/jobs/stages.py::Stage.callables declares.
        for s in INSIGHT_STAGES:
            _check_soft_timeout(job_started_at)
            # Session 05, Part D degenerate case: a repo with zero commits
            # has no contributor data at all -- ExpertiseEngine/
            # TruckFactorEngine would both trivially find nothing, so the
            # whole "knowledge" stage is marked skipped rather than run.
            if s.name == "knowledge" and commit_count == 0:
                mark_stage_skipped(
                    run_id,
                    s.name,
                    session,
                    {"reason": "repo has zero commits; no contributor data to analyze"},
                )
                session.commit()
                continue

            # Session 10, Part E: "security" is the one optional stage --
            # its OSV.dev lookup can fail for reasons entirely outside
            # Compass's control, and that must fail only this stage, never
            # the whole run (app/jobs/stages.py::stage's `optional` param).
            with stage(run_id, s.name, session, optional=(s.name == "security")) as summary:
                assert s.callables  # every insight stage has at least one
                for engine_callable in s.callables:
                    summary.update(engine_callable(ctx, session))
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
            # Session 16, Part B: a run that reaches here always went through
            # the "real mine" branch whenever Facts had actually been evicted
            # (facts_exist above is False the moment app/jobs/eviction.py's
            # wipe_facts ran, which forces reuse_facts=False) -- clearing
            # this unconditionally on every successful run is correct and
            # simplest, since it's already None on the common path where
            # Facts were never evicted in the first place.
            facts_evicted_at=None,
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
