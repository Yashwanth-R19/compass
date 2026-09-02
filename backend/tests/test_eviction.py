import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    File,
    Health,
    Repo,
    RepoPath,
    RepoStatus,
)
from app.jobs.eviction import (
    FACTS_TTL_DAYS,
    KEEP_RUNS_PER_REPO,
    NEVER_EVICT_RUN_AGE_DAYS,
    _evict_stale_facts,
    _prune_excess_superseded_runs,
    run_eviction,
    touch_last_viewed,
)

OLD = timedelta(days=FACTS_TTL_DAYS + 10)
VERY_OLD_RUN = timedelta(days=NEVER_EVICT_RUN_AGE_DAYS + 30)


def _make_repo(
    db_session,
    url: str,
    *,
    is_showcase: bool = False,
    last_viewed_at: datetime | None = None,
    created_at: datetime | None = None,
    head_sha: str | None = "abc123",
) -> Repo:
    repo = Repo(
        url=url,
        owner="fixture",
        name="repo",
        status=RepoStatus.ready,
        is_showcase=is_showcase,
        last_viewed_at=last_viewed_at,
        head_sha=head_sha,
    )
    db_session.add(repo)
    db_session.commit()
    if created_at is not None:
        repo.created_at = created_at
        db_session.commit()
    db_session.refresh(repo)
    return repo


def _add_file(db_session, repo_id: uuid.UUID, path: str, *, now: datetime) -> None:
    repo_path = RepoPath(repo_id=repo_id, path=path)
    db_session.add(repo_path)
    db_session.flush()
    db_session.add(
        File(repo_id=repo_id, path_id=repo_path.id, path=path, first_seen=now, last_seen=now)
    )
    db_session.commit()


def _make_run(
    db_session, repo_id: uuid.UUID, *, status: AnalysisRunStatus, started_at: datetime
) -> AnalysisRun:
    run = AnalysisRun(repo_id=repo_id, status=status, head_sha="abc123", started_at=started_at)
    db_session.add(run)
    db_session.commit()
    return run


def test_never_evicts_showcase_repo_even_when_oldest_and_least_viewed(db_session):
    """Session 16 Known Hazard #1: the showcase repo here is deliberately
    the WORST case -- oldest creation date, never viewed, and buried in
    excess superseded runs -- and must still come out completely untouched
    by both eviction steps."""
    now = datetime.now(UTC)
    showcase = _make_repo(
        db_session,
        "https://github.com/fixture/showcase",
        is_showcase=True,
        last_viewed_at=None,
        created_at=now - OLD * 3,
    )
    ordinary = _make_repo(
        db_session,
        "https://github.com/fixture/ordinary",
        is_showcase=False,
        last_viewed_at=None,
        created_at=now - OLD * 3,
    )

    showcase_current = _make_run(
        db_session, showcase.id, status=AnalysisRunStatus.ready, started_at=now - OLD
    )
    showcase.current_run_id = showcase_current.id
    db_session.commit()
    showcase_run_ids = [showcase_current.id]
    for i in range(KEEP_RUNS_PER_REPO + 3):
        run = _make_run(
            db_session,
            showcase.id,
            status=AnalysisRunStatus.superseded,
            started_at=now - OLD - timedelta(days=i),
        )
        showcase_run_ids.append(run.id)

    ordinary_current = _make_run(
        db_session, ordinary.id, status=AnalysisRunStatus.ready, started_at=now - OLD
    )
    ordinary.current_run_id = ordinary_current.id
    db_session.commit()
    for i in range(KEEP_RUNS_PER_REPO + 3):
        _make_run(
            db_session,
            ordinary.id,
            status=AnalysisRunStatus.superseded,
            started_at=now - OLD - timedelta(days=i),
        )

    _add_file(db_session, showcase.id, "a.py", now=now)
    _add_file(db_session, ordinary.id, "a.py", now=now)

    pruned = _prune_excess_superseded_runs(db_session, now=now)
    db_session.commit()
    evicted = _evict_stale_facts(db_session, now=now)
    db_session.commit()

    # The ordinary repo lost its excess superseded runs and had Facts wiped.
    assert pruned >= 1
    assert evicted == 1

    # The showcase repo: every run it ever had still exists, exactly as
    # created, and its Facts are untouched.
    remaining_showcase_runs = db_session.scalars(
        select(AnalysisRun.id).where(AnalysisRun.repo_id == showcase.id)
    ).all()
    assert set(remaining_showcase_runs) == set(showcase_run_ids)

    db_session.refresh(showcase)
    assert showcase.facts_evicted_at is None
    showcase_files = db_session.scalars(select(File).where(File.repo_id == showcase.id)).all()
    assert len(showcase_files) == 1

    db_session.refresh(ordinary)
    assert ordinary.facts_evicted_at is not None
    ordinary_files = db_session.scalars(select(File).where(File.repo_id == ordinary.id)).all()
    assert len(ordinary_files) == 0


def test_current_run_is_never_a_pruning_candidate(db_session):
    now = datetime.now(UTC)
    repo = _make_repo(db_session, "https://github.com/fixture/current-run-safe")
    current = _make_run(
        db_session, repo.id, status=AnalysisRunStatus.ready, started_at=now - VERY_OLD_RUN
    )
    repo.current_run_id = current.id
    db_session.commit()

    pruned = _prune_excess_superseded_runs(db_session, now=now)
    db_session.commit()

    assert pruned == 0
    assert db_session.get(AnalysisRun, current.id) is not None


def test_prune_keeps_most_recent_n_superseded_runs_oldest_first(db_session):
    now = datetime.now(UTC)
    repo = _make_repo(db_session, "https://github.com/fixture/prune-keep-n")
    run_ids_newest_first = []
    for i in range(KEEP_RUNS_PER_REPO + 2):
        run = _make_run(
            db_session,
            repo.id,
            status=AnalysisRunStatus.superseded,
            started_at=now - VERY_OLD_RUN - timedelta(days=i),
        )
        run_ids_newest_first.append(run.id)
    # run_ids_newest_first[0] has i=0 -> started_at closest to `now` -> newest.

    pruned = _prune_excess_superseded_runs(db_session, now=now)
    db_session.commit()

    assert pruned == 2
    remaining = set(
        db_session.scalars(select(AnalysisRun.id).where(AnalysisRun.repo_id == repo.id)).all()
    )
    assert remaining == set(run_ids_newest_first[:KEEP_RUNS_PER_REPO])


def test_prune_never_touches_a_run_younger_than_the_never_evict_window(db_session):
    now = datetime.now(UTC)
    repo = _make_repo(db_session, "https://github.com/fixture/prune-recent-safe")
    # More than KEEP_RUNS_PER_REPO superseded runs, but all of them recent --
    # none should be pruned even though there are "excess" ones by count.
    for i in range(KEEP_RUNS_PER_REPO + 3):
        _make_run(
            db_session,
            repo.id,
            status=AnalysisRunStatus.superseded,
            started_at=now - timedelta(days=1, hours=i),
        )

    pruned = _prune_excess_superseded_runs(db_session, now=now)
    db_session.commit()

    assert pruned == 0


def test_evict_stale_facts_wipes_facts_but_leaves_insight_intact(db_session):
    now = datetime.now(UTC)
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/facts-ttl",
        last_viewed_at=now - OLD,
        created_at=now - OLD * 2,
    )
    run = _make_run(db_session, repo.id, status=AnalysisRunStatus.ready, started_at=now - OLD)
    repo.current_run_id = run.id
    db_session.commit()

    db_session.add(
        Commit(
            repo_id=repo.id,
            sha="a" * 40,
            author_name="x",
            author_email="x@x.com",
            committed_at=now,
            message="m",
        )
    )
    db_session.add(
        Health(
            analysis_run_id=run.id,
            repo_id=repo.id,
            score=80.0,
            high_risk_ratio=0.1,
            cycle_count=0,
            hidden_dependency_count=0,
        )
    )
    db_session.commit()
    _add_file(db_session, repo.id, "a.py", now=now)

    evicted = _evict_stale_facts(db_session, now=now)
    db_session.commit()

    assert evicted == 1
    assert db_session.scalar(select(File).where(File.repo_id == repo.id)) is None
    assert db_session.scalar(select(Commit).where(Commit.repo_id == repo.id)) is None
    # Insight for the current run is untouched.
    assert db_session.scalar(select(Health).where(Health.analysis_run_id == run.id)) is not None

    db_session.refresh(repo)
    assert repo.facts_evicted_at is not None


def test_evict_stale_facts_skips_a_recently_viewed_repo(db_session):
    now = datetime.now(UTC)
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/facts-recent",
        last_viewed_at=now - timedelta(days=1),
        created_at=now - OLD * 2,
    )
    _add_file(db_session, repo.id, "a.py", now=now)

    evicted = _evict_stale_facts(db_session, now=now)
    db_session.commit()

    assert evicted == 0
    assert db_session.scalar(select(File).where(File.repo_id == repo.id)) is not None


def test_evict_stale_facts_skips_a_repo_with_no_facts_yet(db_session):
    now = datetime.now(UTC)
    _make_repo(
        db_session,
        "https://github.com/fixture/never-analyzed",
        last_viewed_at=None,
        created_at=now - OLD * 2,
        head_sha=None,
    )

    evicted = _evict_stale_facts(db_session, now=now)
    db_session.commit()

    assert evicted == 0


def test_run_eviction_is_a_noop_below_the_high_water_mark(db_session):
    report = run_eviction(db_session)
    assert report.triggered is False
    assert report.runs_pruned == 0
    assert report.repos_facts_evicted == 0
    assert report.vacuumed is False


def test_run_eviction_full_flow_when_triggered(db_session, monkeypatch):
    """Simulates crossing the high-water mark without needing a real
    multi-hundred-MB database -- monkeypatches the ONE function eviction.py
    imported by name (patched here, not on app.db.storage, per the same
    "patch where it's used" rule tests/conftest.py's own db_session fixture
    already documents). Storage genuinely drops from 0.8x to 0.5x of the
    limit across the report's before/after -- exercises the real prune +
    evict-facts + VACUUM path end to end."""
    import app.jobs.eviction as eviction_module
    from app.db.storage import NEON_FREE_TIER_LIMIT_BYTES

    now = datetime.now(UTC)
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/full-flow",
        last_viewed_at=None,
        created_at=now - OLD * 2,
    )
    for i in range(KEEP_RUNS_PER_REPO + 2):
        _make_run(
            db_session,
            repo.id,
            status=AnalysisRunStatus.superseded,
            started_at=now - VERY_OLD_RUN - timedelta(days=i),
        )
    _add_file(db_session, repo.id, "a.py", now=now)

    before_bytes = int(NEON_FREE_TIER_LIMIT_BYTES * 0.80)  # above EVICTION_HIGH_WATER (0.75)
    after_prune_bytes = before_bytes  # still above EVICTION_LOW_WATER (0.55) -- keep evicting
    after_bytes = int(NEON_FREE_TIER_LIMIT_BYTES * 0.50)
    sizes = iter([before_bytes, after_prune_bytes, after_bytes])
    monkeypatch.setattr(eviction_module, "get_database_size_bytes", lambda session: next(sizes))

    report = run_eviction(db_session, now=now)

    assert report.triggered is True
    assert report.runs_pruned == 2
    assert report.repos_facts_evicted == 1
    assert report.vacuumed is True
    assert report.storage_before_bytes == before_bytes
    assert report.storage_after_bytes == after_bytes
    assert report.reclaimed_bytes == before_bytes - after_bytes

    db_session.refresh(repo)
    assert repo.facts_evicted_at is not None


def test_touch_last_viewed_throttled_to_once_per_hour(db_session):
    now = datetime.now(UTC)
    repo = _make_repo(db_session, "https://github.com/fixture/touch-throttle", last_viewed_at=now)

    touch_last_viewed(repo.id, db_session, now=now + timedelta(minutes=30))
    db_session.refresh(repo)
    assert repo.last_viewed_at == now  # unchanged -- within the hour window

    later = now + timedelta(hours=2)
    touch_last_viewed(repo.id, db_session, now=later)
    db_session.refresh(repo)
    assert repo.last_viewed_at == later
