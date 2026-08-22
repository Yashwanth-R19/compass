import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Repo,
    RepoStatus,
    StageStatus,
)
from app.jobs.reaper import STALE_AFTER_MINUTES, reap_stale_runs


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def _make_run(db_session, repo_id: uuid.UUID, *, started_at: datetime) -> uuid.UUID:
    run = AnalysisRun(
        repo_id=repo_id,
        status=AnalysisRunStatus.running,
        head_sha="test-sha",
        started_at=started_at,
    )
    db_session.add(run)
    db_session.commit()
    return run.id


def test_reaper_marks_a_stale_running_run_failed(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/reaper-stale")
    now = datetime.now(UTC)
    stale_started_at = now - timedelta(minutes=STALE_AFTER_MINUTES + 5)
    run_id = _make_run(db_session, repo_id, started_at=stale_started_at)

    db_session.add(AnalysisStage(run_id=run_id, name="coupling", status=StageStatus.running))
    db_session.add(AnalysisStage(run_id=run_id, name="architecture", status=StageStatus.pending))
    db_session.commit()

    reaped = reap_stale_runs(db_session, now=now)
    db_session.commit()

    assert reaped == 1
    run = db_session.get(AnalysisRun, run_id)
    assert run.status == AnalysisRunStatus.failed
    assert run.error is not None
    assert run.finished_at is not None

    stages = {
        s.name: s.status
        for s in db_session.query(AnalysisStage).filter(AnalysisStage.run_id == run_id)
    }
    assert stages["coupling"] == StageStatus.failed
    assert stages["architecture"] == StageStatus.failed


def test_reaper_leaves_a_fresh_running_run_alone(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/reaper-fresh")
    now = datetime.now(UTC)
    fresh_started_at = now - timedelta(minutes=2)
    run_id = _make_run(db_session, repo_id, started_at=fresh_started_at)
    db_session.commit()

    reaped = reap_stale_runs(db_session, now=now)
    db_session.commit()

    assert reaped == 0
    run = db_session.get(AnalysisRun, run_id)
    assert run.status == AnalysisRunStatus.running
    assert run.error is None


def test_reaper_leaves_already_finished_runs_alone(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/reaper-done")
    now = datetime.now(UTC)
    stale_started_at = now - timedelta(minutes=STALE_AFTER_MINUTES + 5)
    run_id = _make_run(db_session, repo_id, started_at=stale_started_at)
    run = db_session.get(AnalysisRun, run_id)
    run.status = AnalysisRunStatus.ready
    run.finished_at = now
    db_session.commit()

    reaped = reap_stale_runs(db_session, now=now)
    db_session.commit()

    assert reaped == 0
    run = db_session.get(AnalysisRun, run_id)
    assert run.status == AnalysisRunStatus.ready
