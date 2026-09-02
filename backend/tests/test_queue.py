"""session 14, Part A/F -- the run queue. The round-robin fairness test is
THE critical one (Known Hazard #3: round-robin is easy to write as FIFO by
accident) -- write it first, per the session prompt's own instruction.
"""

import uuid

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Repo,
    RepoStatus,
    StageStatus,
    User,
)
from app.jobs.queue import create_queued_run, dispatch_pending, select_runs_to_dispatch


def _make_repo(db_session, name: str) -> Repo:
    repo = Repo(url=f"https://github.com/o/{name}", owner="o", name=name, status=RepoStatus.pending)
    db_session.add(repo)
    db_session.flush()
    return repo


def _make_user(db_session, github_id: int) -> User:
    user = User(github_id=github_id, github_login=f"user-{github_id}")
    db_session.add(user)
    db_session.flush()
    return user


def _queue_n(db_session, user_id, count: int, *, name_prefix: str) -> list[uuid.UUID]:
    ids = []
    for i in range(count):
        repo = _make_repo(db_session, f"{name_prefix}-{i}")
        run, _job = create_queued_run(repo.id, db_session, triggered_by_user_id=user_id)
        ids.append(run.id)
    db_session.commit()
    return ids


def test_create_queued_run_prepopulates_stages(db_session):
    repo = _make_repo(db_session, "repo1")
    run, job = create_queued_run(repo.id, db_session, triggered_by_user_id=None)
    db_session.commit()

    assert run.status == AnalysisRunStatus.queued
    assert run.queued_at is not None
    stages = db_session.query(AnalysisStage).filter(AnalysisStage.run_id == run.id).all()
    assert stages, "queued run must have its analysis_stages pre-created"
    assert all(s.status == StageStatus.pending for s in stages)


def test_round_robin_does_not_starve_a_second_user(db_session):
    """The entire reason this module exists: user A queues 50 repositories,
    user B queues just 1 -- B's run must dispatch within the first few
    selections, never after all 50 of A's."""
    user_a = _make_user(db_session, 1001)
    user_b = _make_user(db_session, 1002)

    _queue_n(db_session, user_a.id, 50, name_prefix="a")
    b_run_ids = _queue_n(db_session, user_b.id, 1, name_prefix="b")
    db_session.commit()

    selected = select_runs_to_dispatch(db_session, limit=3)
    assert len(selected) == 3

    selected_ids = [r.id for r in selected]
    assert b_run_ids[0] in selected_ids, (
        "user B's single queued run must be picked in the first few slots, "
        "not starved behind user A's 50"
    )
    # Specifically: round-robin picks A's first, then B's first, in that
    # order (both queued before any of A's later ones) -- B is position 2.
    assert selected_ids[1] == b_run_ids[0]


def test_round_robin_cycles_fairly_across_more_than_two_users(db_session):
    user_a = _make_user(db_session, 2001)
    user_b = _make_user(db_session, 2002)
    user_c = _make_user(db_session, 2003)

    a_ids = _queue_n(db_session, user_a.id, 3, name_prefix="a")
    b_ids = _queue_n(db_session, user_b.id, 3, name_prefix="b")
    c_ids = _queue_n(db_session, user_c.id, 3, name_prefix="c")
    db_session.commit()

    selected = select_runs_to_dispatch(db_session, limit=9)
    selected_ids = [r.id for r in selected]

    # Round 1: one from each user, in queue order (a, b, c).
    assert selected_ids[0:3] == [a_ids[0], b_ids[0], c_ids[0]]
    # Round 2 and 3 continue the same rotation.
    assert selected_ids[3:6] == [a_ids[1], b_ids[1], c_ids[1]]
    assert selected_ids[6:9] == [a_ids[2], b_ids[2], c_ids[2]]


def test_select_runs_to_dispatch_respects_limit(db_session):
    user_a = _make_user(db_session, 3001)
    _queue_n(db_session, user_a.id, 10, name_prefix="a")
    db_session.commit()

    assert len(select_runs_to_dispatch(db_session, limit=0)) == 0
    assert len(select_runs_to_dispatch(db_session, limit=4)) == 4


def test_dispatch_pending_never_exceeds_concurrency_cap(db_session, monkeypatch):
    """Two runs already 'running' + COMPASS_MAX_CONCURRENT_RUNS=3 leaves
    exactly one free slot -- dispatch_pending must select at most that many,
    regardless of how many are queued."""
    from app.config import settings

    monkeypatch.setattr(settings, "COMPASS_MAX_CONCURRENT_RUNS", 3)

    repo1 = _make_repo(db_session, "running1")
    repo2 = _make_repo(db_session, "running2")
    db_session.add(
        AnalysisRun(repo_id=repo1.id, status=AnalysisRunStatus.running, head_sha="a" * 40)
    )
    db_session.add(
        AnalysisRun(repo_id=repo2.id, status=AnalysisRunStatus.running, head_sha="b" * 40)
    )
    db_session.commit()

    user_a = _make_user(db_session, 4001)
    _queue_n(db_session, user_a.id, 5, name_prefix="cap")
    db_session.commit()

    selected = select_runs_to_dispatch(db_session, limit=100)
    running_count = 2
    available = settings.COMPASS_MAX_CONCURRENT_RUNS - running_count
    assert available == 1

    # dispatch_pending computes exactly this "available" cap internally --
    # verified indirectly by calling it with an actual failing runner (no
    # real git clone needed): the repo URLs here are fake, so
    # run_ingestion_job will fail fast at the clone step, but dispatch_pending
    # must still have SELECTED only `available` runs before attempting them.
    dispatched = dispatch_pending(db_session)
    assert len(dispatched) == available
    assert len(selected) >= available  # the pool had more than enough to pick from


def test_estimate_wait_seconds_zero_for_first_position(db_session):
    from app.jobs.queue import estimate_wait_seconds

    assert estimate_wait_seconds(0, db_session) == 0.0
    assert estimate_wait_seconds(1, db_session) == 0.0  # first slot, no rounds ahead
