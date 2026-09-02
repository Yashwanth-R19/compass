"""The portfolio run queue (session 14, Part A).

Session 02 deliberately did NOT build a queue -- excess ``POST /repos``
submissions were rejected outright with a 429 (``app/api/limits.py::
check_concurrency_cap``), and that rejection behavior is UNCHANGED for
single-repo submissions; this module is additive, used only by
``POST /portfolio/analyze`` (``app/api/portfolio.py``).

**Round-robin, not FIFO -- this is the entire point of this module.** A
plain ``ORDER BY queued_at`` over every queued run is FIFO by accident
(session 14 Known Hazard #3): if user A queues 50 repositories and user B
queues 1, FIFO makes B wait behind all 50 of A's. ``select_runs_to_dispatch``
instead groups queued runs by ``triggered_by_user_id`` and takes ONE run per
user per pass, cycling through users (ordered by whichever queued earliest)
until ``limit`` runs are collected or every queue is empty -- B's run is
picked in the very first pass, right after A's first.

No always-on process drains this queue. ``app/jobs/reaper.py`` (session 01)
already runs on a schedule (a 15-minute cron via ``.github/workflows/
reaper.yml``) to mark stale runs failed; session 14 extends that SAME
schedule to also call ``dispatch_pending`` after reaping, so the queue drains
a few runs at a time on each reaper tick, without a second workflow or an
always-on worker.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AnalysisRun, AnalysisRunStatus, Job, JobStatus
from app.jobs.stages import create_pending_stages

logger = logging.getLogger(__name__)

DEFAULT_RUN_DURATION_ESTIMATE_SECONDS = 120.0
"""Fallback used by ``estimate_wait_seconds`` when there is no completed-run
history yet to average -- roughly the middle of plan/RULES.md sec 14's
performance budget (well under the 180s end-to-end target for a repo at the
size cap, comfortably above a small repo's real duration), just enough to
give ``GET /portfolio/queue`` a non-zero estimate on a fresh deployment
rather than reporting 0 seconds for a queue that plainly isn't instant."""

RUN_DURATION_SAMPLE_SIZE = 20
"""How many of the most recent finished runs (ready or failed -- both
represent real elapsed wall-clock time) feed the average duration estimate."""


def create_queued_run(
    repo_id: uuid.UUID, session: Session, triggered_by_user_id: uuid.UUID | None
) -> tuple[AnalysisRun, Job]:
    """Creates an ``analysis_runs`` row with ``status=queued`` (its
    ``analysis_stages`` pre-created as ``pending``, same as a normal run --
    see ``app/jobs/stages.py::create_pending_stages`` -- so ``GET
    /repos/{id}/status`` renders a full stage list immediately even before
    the run is dispatched) plus a matching ``jobs`` row, WITHOUT dispatching
    it. Caller (``POST /portfolio/analyze``) owns the transaction, same
    convention as every other DB-writing function in this codebase that
    isn't itself an engine.
    """
    now = datetime.now(UTC)
    run = AnalysisRun(
        repo_id=repo_id,
        status=AnalysisRunStatus.queued,
        head_sha="",
        triggered_by_user_id=triggered_by_user_id,
        queued_at=now,
    )
    session.add(run)
    session.flush()
    create_pending_stages(run.id, session)

    job = Job(repo_id=repo_id, job_type="ingestion", status=JobStatus.queued, progress=0)
    session.add(job)
    session.flush()

    return run, job


def select_runs_to_dispatch(session: Session, limit: int) -> list[AnalysisRun]:
    """Round-robin selection of up to ``limit`` queued runs, fair ACROSS
    USERS (session 14 Part A/F -- the fairness test this function exists to
    satisfy). Pure read logic, no mutation -- safe and cheap to call from a
    test without touching ``status`` at all.

    Algorithm: group every ``status=queued`` run by
    ``triggered_by_user_id`` (``None`` -- no authenticated submitter --
    is its own bucket, same as any other key), order each user's own queue
    FIFO by ``queued_at``, order the USERS themselves by their earliest
    ``queued_at`` (whoever queued first gets the first slot in each round),
    then take one run per user per pass, cycling, until ``limit`` is reached
    or every bucket is empty.
    """
    if limit <= 0:
        return []

    rows = list(
        session.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.status == AnalysisRunStatus.queued)
            .order_by(AnalysisRun.queued_at.asc(), AnalysisRun.id.asc())
        )
    )
    if not rows:
        return []

    by_user: dict[uuid.UUID | None, list[AnalysisRun]] = defaultdict(list)
    for row in rows:
        by_user[row.triggered_by_user_id].append(row)

    # `rows` is already queued_at-ascending, so each bucket's list is
    # already FIFO within itself -- and the user key order below (by that
    # user's OWN first row's position in `rows`) is exactly "whoever queued
    # earliest goes first in the rotation", with no second sort needed.
    user_order = list(dict.fromkeys(row.triggered_by_user_id for row in rows))

    selected: list[AnalysisRun] = []
    cursors: dict[uuid.UUID | None, int] = {u: 0 for u in user_order}
    while len(selected) < limit:
        made_progress = False
        for user in user_order:
            if len(selected) >= limit:
                break
            queue = by_user[user]
            cursor = cursors[user]
            if cursor >= len(queue):
                continue
            selected.append(queue[cursor])
            cursors[user] = cursor + 1
            made_progress = True
        if not made_progress:
            break

    return selected


def dispatch_pending(session: Session, limit: int | None = None) -> list[AnalysisRun]:
    """Dispatches up to ``COMPASS_MAX_CONCURRENT_RUNS`` minus however many
    runs are currently ``running`` -- called on a schedule (the reaper) and
    right after a run completes. Runs each selected job SYNCHRONOUSLY, in
    this process -- there is no always-on worker to hand off to, matching
    this module's own docstring; a reaper tick that dispatches N runs blocks
    for roughly N times a single ingestion run's duration before returning.

    Returns the list of ``AnalysisRun`` rows that were dispatched (for
    logging/testing) -- each one's status has already moved past ``queued``
    by the time this returns (either ``ready``/``failed`` from having
    actually run, since dispatch happens inline, or an exception was raised
    and caught per-run so one bad repo doesn't stop the rest of the batch
    from being tried).
    """
    running = (
        session.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(AnalysisRun.status == AnalysisRunStatus.running)
        )
        or 0
    )
    cap = limit if limit is not None else settings.COMPASS_MAX_CONCURRENT_RUNS
    available = cap - running
    if available <= 0:
        return []

    selected = select_runs_to_dispatch(session, available)
    dispatched: list[AnalysisRun] = []
    for run in selected:
        job = session.scalar(
            select(Job)
            .where(Job.repo_id == run.repo_id, Job.status == JobStatus.queued)
            .order_by(Job.created_at.asc())
        )
        if job is None:
            logger.warning("dispatch_pending: no queued Job row found for run %s", run.id)
            continue

        # Imported locally (not at module top) to avoid a circular import --
        # app/jobs/runner.py doesn't import this module, but importing it
        # eagerly at the top of this file would still tie queue.py's own
        # import time to runner.py's (git/tree-sitter/etc.) dependency
        # chain, which every other lightweight, DB-only helper in
        # app/jobs/ (dispatch.py, reaper.py) already avoids the same way.
        from app.jobs.runner import run_ingestion_job

        try:
            run_ingestion_job(
                run.repo_id,
                job.id,
                worker_mode="inline",
                triggered_by_user_id=run.triggered_by_user_id,
                existing_analysis_run_id=run.id,
            )
        except Exception:
            # run_ingestion_job already marked the run/job/repo failed and
            # logged internally before re-raising -- one repo's failure
            # must not stop the rest of this batch from being dispatched.
            logger.warning("dispatch_pending: run %s failed", run.id, exc_info=True)
        dispatched.append(run)

    return dispatched


def queue_position(run_id: uuid.UUID, session: Session) -> int | None:
    """1-based position of ``run_id`` within the current round-robin
    dispatch order -- ``None`` if it isn't (or is no longer) queued.
    Computed by running the SAME selection the dispatcher uses, out to a
    large enough limit to cover the whole queue, and finding the index --
    this guarantees "position" always means exactly what will actually
    happen next, not a separate, potentially-diverging FIFO count."""
    run = session.get(AnalysisRun, run_id)
    if run is None or run.status != AnalysisRunStatus.queued:
        return None

    total_queued = (
        session.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(AnalysisRun.status == AnalysisRunStatus.queued)
        )
        or 0
    )
    ordered = select_runs_to_dispatch(session, total_queued)
    for i, row in enumerate(ordered):
        if row.id == run_id:
            return i + 1
    return None


def _average_run_duration_seconds(session: Session) -> float:
    rows = session.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.status.in_((AnalysisRunStatus.ready, AnalysisRunStatus.failed)),
            AnalysisRun.finished_at.is_not(None),
        )
        .order_by(AnalysisRun.finished_at.desc())
        .limit(RUN_DURATION_SAMPLE_SIZE)
    ).all()
    durations = [
        (r.finished_at - r.started_at).total_seconds()
        for r in rows
        if r.finished_at is not None and r.finished_at > r.started_at
    ]
    if not durations:
        return DEFAULT_RUN_DURATION_ESTIMATE_SECONDS
    return sum(durations) / len(durations)


def estimate_wait_seconds(position: int, session: Session) -> float:
    """A rough ETA for a run at 1-based queue ``position``: how many more
    "rounds" of ``COMPASS_MAX_CONCURRENT_RUNS`` concurrent slots have to
    clear before this one's turn, times the average recent run duration.
    Deliberately rough -- real run durations vary hugely by repo size --
    but a rough estimate ("about 4 minutes") is what lets the UI say
    something better than a silent stall (Part A)."""
    if position <= 0:
        return 0.0
    slots = max(1, settings.COMPASS_MAX_CONCURRENT_RUNS)
    rounds_ahead = (position - 1) // slots
    return rounds_ahead * _average_run_duration_seconds(session)


__all__ = [
    "create_queued_run",
    "dispatch_pending",
    "estimate_wait_seconds",
    "queue_position",
    "select_runs_to_dispatch",
]
