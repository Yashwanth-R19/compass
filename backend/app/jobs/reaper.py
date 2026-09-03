"""Marks stuck analysis runs failed (session 01, Part H).

Without this, a runner that dies mid-run -- OOM, a workflow timeout, a
cancelled Actions run, a crashed inline BackgroundTasks worker -- leaves its
``analysis_runs`` row (and any of its ``analysis_stages`` rows still
``pending``/``running``) stuck in ``running`` forever, and the repo page
shows a spinner that never resolves. ``.github/workflows/reaper.yml`` runs
this on a schedule (every 15 minutes) via ``python -m app.jobs.reaper``, kept
as testable Python rather than SQL embedded in the workflow YAML.

Implemented as plain, pure-DB logic -- no git/network/filesystem -- same
discipline as the analysis engines, just not one of them (this isn't part
of the Insight computation, it's operational housekeeping).
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.db.models import AnalysisRun, AnalysisRunStatus, AnalysisStage, StageStatus
from app.jobs.eviction import run_eviction
from app.jobs.log_redaction import install_log_redaction

logger = logging.getLogger(__name__)

STALE_AFTER_MINUTES = 20
"""A run still `running` after this long is presumed dead, not just slow --
comfortably above mine.yml's own 15-minute `timeout-minutes` (session 01,
Part H), so the workflow's own timeout is always what fires first for a
genuinely-still-working run; this only catches what even that step missed
(e.g. the runner process was killed outright, or GitHub's own infra dropped
the job) or the inline-BackgroundTasks equivalent."""


def reap_stale_runs(session: Session, *, now: datetime | None = None) -> int:
    """Marks every ``analysis_runs`` row still ``running`` after
    ``STALE_AFTER_MINUTES`` as ``failed`` with a timeout error, and marks its
    ``pending``/``running`` stages ``failed`` too. Returns the number of runs
    reaped. Caller owns the transaction (same convention as the engines and
    app/db/wipe.py) -- this function only mutates and does not commit.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=STALE_AFTER_MINUTES)

    stale_runs = session.scalars(
        select(AnalysisRun).where(
            AnalysisRun.status == AnalysisRunStatus.running,
            AnalysisRun.started_at < cutoff,
        )
    ).all()

    for run in stale_runs:
        run.status = AnalysisRunStatus.failed
        run.error = f"Timed out: still running after {STALE_AFTER_MINUTES} minutes."
        run.finished_at = now or datetime.now(UTC)

        stale_stages = session.scalars(
            select(AnalysisStage).where(
                AnalysisStage.run_id == run.id,
                AnalysisStage.status.in_((StageStatus.pending, StageStatus.running)),
            )
        ).all()
        for stage_row in stale_stages:
            stage_row.status = StageStatus.failed
            stage_row.error = "Run timed out."
            stage_row.finished_at = now or datetime.now(UTC)

    return len(stale_runs)


def main() -> int:
    # Install the same redacting log filter worker.py installs, before
    # running anything -- reaper.yml is also a public repository's workflow
    # (CLAUDE.md's public-logs constraint), and this is cheap insurance even
    # though neither reap_stale_runs nor run_eviction currently logs
    # anything sensitive.
    install_log_redaction()

    session = SessionLocal()
    try:
        reaped = reap_stale_runs(session)
        session.commit()
        logger.info("reaper: marked %d stale run(s) failed", reaped)

        # Session 16, Part B: no always-on process drains eviction either --
        # this same 15-minute cron tick is what checks storage and evicts
        # when needed, right after reaping, same "attach to the reaper's
        # existing schedule rather than a second workflow" precedent. A
        # no-op (storage comfortably under the high-water mark) costs one
        # cheap pg_database_size() query.
        eviction_report = run_eviction(session)
        if eviction_report.triggered:
            logger.info(
                "reaper: eviction pruned %d run(s), evicted facts for %d repo(s), "
                "reclaimed %d bytes",
                eviction_report.runs_pruned,
                eviction_report.repos_facts_evicted,
                eviction_report.reclaimed_bytes,
            )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
