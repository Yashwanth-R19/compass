import uuid
from datetime import UTC, datetime

import pytest
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
from app.jobs.stages import ALL_STAGES, FACT_STAGES, INSIGHT_STAGES, create_pending_stages, stage


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


# ---------------------------------------------------------------------------
# Session 10, Part E/G: the ``optional`` stage parameter.
# ---------------------------------------------------------------------------


def test_thirteen_stage_final_order(db_session):
    """Session 10 Part F: "13 stages, and this is the end state for the
    whole plan. No later session adds one." -- pins the exact, final
    canonical order."""
    assert [s.name for s in FACT_STAGES] == [
        "clone",
        "mine",
        "structure",
        "persist_facts",
        "secrets",
    ]
    assert [s.name for s in INSIGHT_STAGES] == [
        "coupling",
        "subsystems",
        "architecture",
        "risk",
        "knowledge",
        "onboarding",
        "security",
        "rank",
    ]
    assert len(ALL_STAGES) == 13


def test_optional_stage_that_raises_marks_itself_failed_and_leaves_run_running(db_session):
    """Part E: an optional stage that raises is marked failed with its
    error, and the run continues -- the OWNING analysis_runs row is NOT
    marked failed."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/optional-stage-fail")
    run_id = _make_run(db_session, repo_id)
    create_pending_stages(run_id, db_session)
    db_session.commit()

    # No pytest.raises: optional=True SWALLOWS the exception (see the
    # dedicated swallowing test below) -- reaching this line at all is part
    # of what's under test.
    with stage(run_id, "security", db_session, optional=True):
        raise ValueError("simulated OSV outage")

    stage_row = db_session.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == "security"
        )
    )
    assert stage_row.status == StageStatus.failed
    assert "simulated OSV outage" in stage_row.error

    run_row = db_session.get(AnalysisRun, run_id)
    assert run_row.status == AnalysisRunStatus.running  # untouched, NOT failed
    assert run_row.error is None


def test_optional_stage_swallows_exception_so_caller_can_continue(db_session):
    """The realistic call shape run_ingestion_job actually uses: `with
    stage(..., optional=True):` with no surrounding try/except -- the
    exception must not propagate at all, unlike the non-optional case."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/optional-stage-swallow")
    run_id = _make_run(db_session, repo_id)
    create_pending_stages(run_id, db_session)
    db_session.commit()

    # No pytest.raises here -- reaching the line after the `with` block
    # proves the exception was swallowed.
    with stage(run_id, "security", db_session, optional=True) as summary:
        summary["never_written"] = True
        raise RuntimeError("boom")
    reached_here = True
    assert reached_here

    stage_row = db_session.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == "security"
        )
    )
    assert stage_row.status == StageStatus.failed
    assert stage_row.summary is None  # never committed -- the exception rolled it back


def test_non_optional_stage_that_raises_still_fails_the_whole_run(db_session):
    """The default (optional=False) behavior is unchanged: both the stage
    AND the owning run are marked failed, and the exception re-raises."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/non-optional-stage-fail")
    run_id = _make_run(db_session, repo_id)
    create_pending_stages(run_id, db_session)
    db_session.commit()

    with pytest.raises(RuntimeError), stage(run_id, "risk", db_session):
        raise RuntimeError("real failure")

    stage_row = db_session.scalar(
        select(AnalysisStage).where(AnalysisStage.run_id == run_id, AnalysisStage.name == "risk")
    )
    assert stage_row.status == StageStatus.failed

    run_row = db_session.get(AnalysisRun, run_id)
    assert run_row.status == AnalysisRunStatus.failed
    assert run_row.error == "real failure"


def test_optional_stage_failure_lets_subsequent_stages_still_run(db_session):
    """Part E/G: "lets subsequent stages run" -- a failed optional
    "security" stage must not prevent "rank" from running right after it,
    the exact sequence run_ingestion_job's INSIGHT_STAGES loop relies on."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/optional-stage-continues")
    run_id = _make_run(db_session, repo_id)
    create_pending_stages(run_id, db_session)
    db_session.commit()

    with stage(run_id, "security", db_session, optional=True):
        raise RuntimeError("OSV outage")

    with stage(run_id, "rank", db_session) as summary:
        summary["findings_ranked"] = 0

    rank_row = db_session.scalar(
        select(AnalysisStage).where(AnalysisStage.run_id == run_id, AnalysisStage.name == "rank")
    )
    assert rank_row.status == StageStatus.done

    run_row = db_session.get(AnalysisRun, run_id)
    assert run_row.status == AnalysisRunStatus.running  # the run is still healthy
