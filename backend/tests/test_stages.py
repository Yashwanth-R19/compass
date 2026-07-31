import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Coupling,
    FileMetrics,
    Finding,
    Health,
    Repo,
    RepoPath,
    RepoStatus,
    Severity,
    StageStatus,
)
from app.db.wipe import prune_run
from app.jobs.stages import ALL_STAGES, create_pending_stages


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def _make_run(db_session, repo_id: uuid.UUID) -> uuid.UUID:
    run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.running, head_sha="test-sha")
    db_session.add(run)
    db_session.commit()
    return run.id


def test_create_pending_stages_pre_creates_every_stage_as_pending(db_session):
    """Part G: before any work starts, every stage in the canonical list must
    already exist as a `pending` row -- this is what lets the very first
    /repos/{id}/status poll render the full stage list with skeletons."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/stages-precreate")
    run_id = _make_run(db_session, repo_id)

    create_pending_stages(run_id, db_session)
    db_session.commit()

    rows = db_session.scalars(
        select(AnalysisStage).where(AnalysisStage.run_id == run_id).order_by(AnalysisStage.id)
    ).all()

    assert [r.name for r in rows] == [s.name for s in ALL_STAGES]
    assert all(r.status == StageStatus.pending for r in rows)
    assert all(r.started_at is None and r.finished_at is None and r.summary is None for r in rows)


def _seed_insight_row_set(db_session, repo_id: uuid.UUID, run_id: uuid.UUID, path_id: int) -> None:
    db_session.execute(
        insert(Coupling),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_a_id": path_id,
                "path_b_id": path_id,
                "shared_revs": 5,
                "coupling_degree": 0.5,
                "avg_revs": 5.0,
            }
        ],
    )
    db_session.execute(
        insert(FileMetrics),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_id": path_id,
                "risk_score": 0.5,
                "risk_confidence": 0.5,
                "hotspot_rank": 0,
            }
        ],
    )
    db_session.execute(
        insert(Finding),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "risk",
                "severity": Severity.low,
                "confidence": 0.5,
                "path_id": path_id,
                "evidence_sha": None,
                "title": "synthetic finding",
                "detail": "",
                "rank": 0,
            }
        ],
    )
    db_session.add(
        Health(
            id=uuid.uuid4(),
            analysis_run_id=run_id,
            repo_id=repo_id,
            score=100.0,
            high_risk_ratio=0.0,
            cycle_count=0,
            hidden_dependency_count=0,
            computed_at=datetime.now(UTC),
        )
    )


def test_prune_run_removes_only_that_runs_insight_rows(db_session):
    """Part G: prune_run must delete exactly one run's Insight rows (and the
    run itself), leaving another run of the SAME repo completely untouched --
    this is the operation Phase 21's LRU eviction will call."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/prune-run")
    db_session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": "shared.py"}])
    db_session.commit()
    path_id = db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == "shared.py")
    )

    run_a = _make_run(db_session, repo_id)
    run_b = _make_run(db_session, repo_id)
    _seed_insight_row_set(db_session, repo_id, run_a, path_id)
    _seed_insight_row_set(db_session, repo_id, run_b, path_id)
    db_session.commit()

    prune_run(run_a, db_session)
    db_session.commit()

    assert db_session.get(AnalysisRun, run_a) is None
    assert db_session.scalar(select(Coupling).where(Coupling.analysis_run_id == run_a)) is None
    assert (
        db_session.scalar(select(FileMetrics).where(FileMetrics.analysis_run_id == run_a)) is None
    )
    assert db_session.scalar(select(Finding).where(Finding.analysis_run_id == run_a)) is None
    assert db_session.scalar(select(Health).where(Health.analysis_run_id == run_a)) is None

    # run_b's rows -- same repo_id, same path_id even -- must be untouched.
    assert db_session.get(AnalysisRun, run_b) is not None
    assert db_session.scalar(select(Coupling).where(Coupling.analysis_run_id == run_b)) is not None
    assert (
        db_session.scalar(select(FileMetrics).where(FileMetrics.analysis_run_id == run_b))
        is not None
    )
    assert db_session.scalar(select(Finding).where(Finding.analysis_run_id == run_b)) is not None
    assert db_session.scalar(select(Health).where(Health.analysis_run_id == run_b)) is not None

    # repo_paths is never touched by prune_run -- it's permanent, see
    # app/db/models.py RepoPath docstring.
    assert db_session.scalar(select(RepoPath).where(RepoPath.id == path_id)) is not None
