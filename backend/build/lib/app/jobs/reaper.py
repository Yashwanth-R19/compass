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
    session = SessionLocal()
    try:
        reaped = reap_stale_runs(session)
        session.commit()
        logger.info("reaper: marked %d stale run(s) failed", reaped)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
