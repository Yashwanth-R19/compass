"""Storage eviction (session 16, Part B) -- the policy that keeps Neon's
free-tier storage inside budget indefinitely, with no human intervening.
Built entirely on machinery that already existed but was unused:
``app/db/wipe.py::prune_run`` (implemented and tested since the Phase 02
Facts/Insight split, never wired to anything) and ``wipe_facts`` (used every
re-analysis, reused here for a different trigger).

Policy, applied in this exact order every time ``run_eviction`` is called
(wired into the existing 15-minute reaper cron, ``app/jobs/reaper.py`` --
there is no separate always-on eviction process, same "the reaper's cron tick
is the only driver" precedent session 14's queue dispatcher already set):

1. **Never evict**: showcase repositories (``repos.is_showcase``), the
   current run of any repo (never even considered -- only ``superseded`` runs
   are queried), or any run created in the last ``NEVER_EVICT_RUN_AGE_DAYS``.
   Session 16 Known Hazard #1: this rule is checked FIRST and structurally --
   a showcase repo's runs are excluded from the candidate query entirely,
   not filtered out after the fact, so there is no code path that could
   accidentally prune one.
2. Evict superseded runs beyond the most recent ``KEEP_RUNS_PER_REPO`` per
   repository, oldest first (keeping 3 preserves session 13's compare
   feature -- a user diffing "the last few" runs).
3. If storage is still above ``EVICTION_LOW_WATER`` after step 2, evict
   **Facts** (not Insight) for repositories with no run viewed in
   ``FACTS_TTL_DAYS``. The repository row and its current run's Insight
   (health/risk/passport/...) are untouched and stay fully readable; only a
   fresh re-analysis needs the clone again. ``repos.facts_evicted_at``
   records this so the frontend can render "analysis archived" instead of a
   silently-empty Facts-dependent page (app/api/repos.py's status response).
4. Runs plain ``VACUUM`` (never ``VACUUM FULL`` -- Known Hazard #3) so
   Postgres actually returns freed pages, then reports what was evicted and
   the bytes reclaimed.

Only step 1 (a query filter) is unconditional; steps 2-4 only run once
storage has actually crossed ``EVICTION_HIGH_WATER`` -- this function is a
no-op, cheaply, on every reaper tick where the database is nowhere near the
limit.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, AnalysisRunStatus, Repo
from app.db.storage import (
    EVICTION_HIGH_WATER,
    EVICTION_LOW_WATER,
    NEON_FREE_TIER_LIMIT_BYTES,
    get_database_size_bytes,
    vacuum,
)
from app.db.wipe import prune_run, wipe_facts

logger = logging.getLogger(__name__)

KEEP_RUNS_PER_REPO = 3
"""Superseded runs beyond the most recent N (per repo, newest-first) are
eligible for pruning -- keeping 3 preserves session 13's run-vs-run compare
(picking any two of "the last few" runs), while still bounding how many old
runs' Insight rows a frequently-reanalyzed repo accumulates forever."""

FACTS_TTL_DAYS = 30
"""A repo whose ``last_viewed_at`` (any repo-scoped endpoint resolving it via
``require_repo_access``) is older than this -- or was never set at all, for a
repo old enough that "never viewed" is itself the signal -- has its Facts
wiped. The repository row and its current run's Insight stay intact."""

NEVER_EVICT_RUN_AGE_DAYS = 7
"""No run younger than this is ever pruned, even if already superseded -- a
very recent re-analysis is exactly the kind of run a "before my last few
commits" compare would reach for."""


@dataclass
class EvictionReport:
    triggered: bool = False
    runs_pruned: int = 0
    repos_facts_evicted: int = 0
    vacuumed: bool = False
    storage_before_bytes: int = 0
    storage_after_bytes: int = 0
    reclaimed_bytes: int = 0


def _prune_excess_superseded_runs(session: Session, *, now: datetime) -> int:
    """Step 2. Structurally cannot touch a showcase repo (excluded from the
    outer query) or a repo's current run (``current_run_id`` is always
    ``ready``, never ``superseded``, so it never appears in the inner query
    at all -- two independent guarantees, not one relied on twice)."""
    cutoff = now - timedelta(days=NEVER_EVICT_RUN_AGE_DAYS)
    pruned = 0

    repo_ids = session.scalars(select(Repo.id).where(Repo.is_showcase.is_(False))).all()

    for repo_id in repo_ids:
        superseded_runs = session.scalars(
            select(AnalysisRun)
            .where(
                AnalysisRun.repo_id == repo_id,
                AnalysisRun.status == AnalysisRunStatus.superseded,
            )
            .order_by(AnalysisRun.started_at.desc())
        ).all()

        for run in superseded_runs[KEEP_RUNS_PER_REPO:]:
            if run.started_at >= cutoff:
                continue
            prune_run(run.id, session)
            pruned += 1

    return pruned


def _evict_stale_facts(session: Session, *, now: datetime) -> int:
    """Step 3. Never a showcase repo; never a repo whose Facts are already
    evicted (``facts_evicted_at`` already set); never a repo with no Facts to
    evict in the first place (``head_sha`` still NULL -- it never finished a
    single analysis); never a repo younger than ``FACTS_TTL_DAYS`` itself,
    which is what keeps a brand-new, not-yet-viewed repo (``last_viewed_at``
    still NULL because no repo-scoped request has resolved it yet) from being
    evicted the moment it's created."""
    cutoff = now - timedelta(days=FACTS_TTL_DAYS)

    candidates = session.scalars(
        select(Repo).where(
            Repo.is_showcase.is_(False),
            Repo.facts_evicted_at.is_(None),
            Repo.head_sha.isnot(None),
            Repo.created_at < cutoff,
            or_(Repo.last_viewed_at.is_(None), Repo.last_viewed_at < cutoff),
        )
    ).all()

    for repo in candidates:
        wipe_facts(repo.id, session)
        repo.facts_evicted_at = now
        logger.info(
            "eviction: wiped Facts for repo %s (last viewed %s)", repo.id, repo.last_viewed_at
        )

    return len(candidates)


def _engine_for(session: Session) -> Engine:
    """The real ``Engine`` backing ``session``'s connection -- deliberately
    NOT ``from app.db.base import engine`` (a fixed module-level singleton
    bound to ``settings.DATABASE_URL`` at import time), which under
    ``tests/conftest.py``'s ``db_session`` fixture would silently point at
    whatever ``DATABASE_URL`` happens to be configured in the environment
    (a real developer's ``.env``, in this repo's own case) rather than the
    isolated test database ``db_session`` actually uses -- exactly the
    "tests never touch DATABASE_URL" rule CLAUDE.md states for every other
    DB test in this codebase. ``session.get_bind()`` returns whatever the
    session is ACTUALLY bound to (the test's own ``Connection``, in tests;
    the real pooled ``Engine``, in production) -- unwrapped to its owning
    ``Engine`` either way, since ``vacuum()`` needs to open a fresh,
    independent AUTOCOMMIT connection, not reuse a connection already inside
    an open transaction.
    """
    bind = session.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


def run_eviction(session: Session, *, now: datetime | None = None) -> EvictionReport:
    """The full policy, steps 1-4. Commits after each mutating step (not just
    once at the end) so a VACUUM -- which must run outside any open
    transaction, see ``app/db/storage.py::vacuum`` -- always starts from
    durably persisted state, and so a failure partway through never rolls
    back eviction work already done. Caller (``app/jobs/reaper.py``) is
    expected to call this with a session it owns; this function commits that
    session directly rather than requiring the caller to do it, unlike
    ``reap_stale_runs``' convention -- deliberate, since the VACUUM step
    between commits needs each preceding step to already be durable.
    """
    now = now or datetime.now(UTC)
    report = EvictionReport()
    report.storage_before_bytes = get_database_size_bytes(session)
    report.storage_after_bytes = report.storage_before_bytes

    high_water_bytes = int(NEON_FREE_TIER_LIMIT_BYTES * EVICTION_HIGH_WATER)
    low_water_bytes = int(NEON_FREE_TIER_LIMIT_BYTES * EVICTION_LOW_WATER)

    if report.storage_before_bytes < high_water_bytes:
        return report

    report.triggered = True
    logger.info(
        "eviction: storage %.1f MB is above the high-water mark (%.1f MB) -- starting",
        report.storage_before_bytes / 1024**2,
        high_water_bytes / 1024**2,
    )

    report.runs_pruned = _prune_excess_superseded_runs(session, now=now)
    session.commit()

    if get_database_size_bytes(session) >= low_water_bytes:
        report.repos_facts_evicted = _evict_stale_facts(session, now=now)
        session.commit()

    vacuum(_engine_for(session))
    report.vacuumed = True
    report.storage_after_bytes = get_database_size_bytes(session)
    report.reclaimed_bytes = max(0, report.storage_before_bytes - report.storage_after_bytes)

    logger.info(
        "eviction: pruned %d run(s), evicted facts for %d repo(s), reclaimed %.1f MB "
        "(%.1f MB -> %.1f MB)",
        report.runs_pruned,
        report.repos_facts_evicted,
        report.reclaimed_bytes / 1024**2,
        report.storage_before_bytes / 1024**2,
        report.storage_after_bytes / 1024**2,
    )
    return report


def touch_last_viewed(repo_id: uuid.UUID, session: Session, *, now: datetime | None = None) -> None:
    """Updates ``repos.last_viewed_at`` -- called from
    ``app/auth/deps.py::require_repo_access`` on every repo-scoped request.
    Session 16 Known Hazard #5: a write on every read is fine at this scale,
    but only when it's actually cheap -- a single ``UPDATE`` with no
    ``RETURNING``, and skipped entirely when the existing value is already
    within the last hour, so a burst of requests for the same repo costs at
    most one extra write per hour, not one per request.
    """
    now = now or datetime.now(UTC)
    repo = session.get(Repo, repo_id)
    if repo is None:
        return
    if repo.last_viewed_at is not None and (now - repo.last_viewed_at) < timedelta(hours=1):
        return
    repo.last_viewed_at = now
    session.commit()


__all__ = [
    "FACTS_TTL_DAYS",
    "KEEP_RUNS_PER_REPO",
    "NEVER_EVICT_RUN_AGE_DAYS",
    "EvictionReport",
    "run_eviction",
    "touch_last_viewed",
]
