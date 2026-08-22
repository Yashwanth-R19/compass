import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Coupling,
    Dependency,
    File,
    FileMetrics,
    Repo,
    RepoPath,
    RepoStatus,
)
from app.engines.context import RunContext
from app.engines.health import (
    CYCLE_PENALTY_CAP,
    CYCLE_PENALTY_PER_CYCLE,
    HIDDEN_DEP_PENALTY_CAP,
    HIDDEN_DEP_PENALTY_PER_PAIR,
    RISK_PENALTY_WEIGHT,
    HealthEngine,
)


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


def _intern_paths(db_session, repo_id: uuid.UUID, paths: list[str]) -> dict[str, int]:
    existing = {
        row.path: row.id
        for row in db_session.execute(
            select(RepoPath.path, RepoPath.id).where(RepoPath.repo_id == repo_id)
        ).all()
    }
    new_paths = [p for p in paths if p not in existing]
    if new_paths:
        db_session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": p} for p in new_paths])
        db_session.flush()
        existing = {
            row.path: row.id
            for row in db_session.execute(
                select(RepoPath.path, RepoPath.id).where(RepoPath.repo_id == repo_id)
            ).all()
        }
    return existing


def _add_file_with_risk_score(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, path: str, risk_score: float
) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    now = datetime.now(UTC)
    file = File(
        repo_id=repo_id,
        path_id=path_id,
        path=path,
        language="python",
        current_loc=10,
        complexity=1.0,
        churn_total=1,
        commit_count=1,
        first_seen=now,
        last_seen=now,
        is_deleted=False,
    )
    db_session.add(file)
    db_session.flush()
    db_session.add(
        FileMetrics(
            analysis_run_id=run_id,
            repo_id=repo_id,
            path_id=path_id,
            risk_score=risk_score,
            risk_confidence=0.5,
            hotspot_rank=0,
        )
    )


def _add_deleted_file(db_session, repo_id: uuid.UUID, path: str) -> None:
    """A file with no FileMetrics row -- RiskEngine never scores deleted
    files, so this simulates real deletion history without a risk_score."""
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path=path,
            language="python",
            current_loc=0,
            complexity=0.0,
            churn_total=1,
            commit_count=1,
            first_seen=now,
            last_seen=now,
            is_deleted=True,
        )
    )


def _add_dependency(db_session, repo_id: uuid.UUID, from_path: str, to_path: str) -> None:
    path_ids = _intern_paths(db_session, repo_id, [from_path, to_path])
    db_session.execute(
        insert(Dependency),
        [
            {
                "repo_id": repo_id,
                "from_path_id": path_ids[from_path],
                "to_path_id": path_ids[to_path],
                "dep_type": "import",
            }
        ],
    )


def _add_coupling(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, path_a: str, path_b: str
) -> None:
    path_ids = _intern_paths(db_session, repo_id, [path_a, path_b])
    db_session.execute(
        insert(Coupling),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_a_id": path_ids[path_a],
                "path_b_id": path_ids[path_b],
                "shared_revs": 6,
                "coupling_degree": 0.9,
                "avg_revs": 6.0,
            }
        ],
    )


def test_healthy_repo_scores_100(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-perfect")
    run_id = _make_run(db_session, repo_id)
    for i in range(4):
        _add_file_with_risk_score(db_session, repo_id, run_id, f"f{i}.py", risk_score=0.1)
    db_session.commit()

    result = HealthEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert result["score"] == pytest.approx(100.0)
    assert result["high_risk_ratio"] == pytest.approx(0.0)
    assert result["cycle_count"] == 0
    assert result["hidden_dependency_count"] == 0


def test_penalties_apply_and_are_uncapped_below_threshold(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-penalized")
    run_id = _make_run(db_session, repo_id)
    # 2 of 4 files are high-risk (>= 0.60) -> high_risk_ratio = 0.5
    _add_file_with_risk_score(db_session, repo_id, run_id, "hot1.py", risk_score=0.8)
    _add_file_with_risk_score(db_session, repo_id, run_id, "hot2.py", risk_score=0.7)
    _add_file_with_risk_score(db_session, repo_id, run_id, "ok1.py", risk_score=0.2)
    _add_file_with_risk_score(db_session, repo_id, run_id, "ok2.py", risk_score=0.3)

    # One 2-file cycle: x.py <-> y.py
    _add_dependency(db_session, repo_id, "x.py", "y.py")
    _add_dependency(db_session, repo_id, "y.py", "x.py")

    # One hidden dependency: m.py/n.py coupled, no structural edge between them.
    _add_coupling(db_session, repo_id, run_id, "m.py", "n.py")
    db_session.commit()

    result = HealthEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert result["high_risk_ratio"] == pytest.approx(0.5)
    assert result["cycle_count"] == 1
    assert result["hidden_dependency_count"] == 1

    expected_score = (
        100.0 - (RISK_PENALTY_WEIGHT * 0.5) - CYCLE_PENALTY_PER_CYCLE - HIDDEN_DEP_PENALTY_PER_PAIR
    )
    assert result["score"] == pytest.approx(expected_score)


def test_penalties_are_capped_and_score_floors_at_zero(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-floor")
    run_id = _make_run(db_session, repo_id)
    # All files high-risk -> high_risk_ratio = 1.0 -> risk_penalty = 40 (uncapped, <=100)
    for i in range(3):
        _add_file_with_risk_score(db_session, repo_id, run_id, f"hot{i}.py", risk_score=0.9)
    db_session.commit()

    # Many small planted cycles so CYCLE_PENALTY_PER_CYCLE * count exceeds the cap.
    cycles_needed = int(CYCLE_PENALTY_CAP // CYCLE_PENALTY_PER_CYCLE) + 3
    for i in range(cycles_needed):
        _add_dependency(db_session, repo_id, f"p{i}.py", f"q{i}.py")
        _add_dependency(db_session, repo_id, f"q{i}.py", f"p{i}.py")

    # Many hidden-dependency pairs so their penalty also exceeds its cap.
    pairs_needed = int(HIDDEN_DEP_PENALTY_CAP // HIDDEN_DEP_PENALTY_PER_PAIR) + 3
    for i in range(pairs_needed):
        _add_coupling(db_session, repo_id, run_id, f"m{i}.py", f"n{i}.py")
    db_session.commit()

    result = HealthEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert result["cycle_count"] == cycles_needed
    assert result["hidden_dependency_count"] == pairs_needed
    # 40 (risk) + 30 (cycle cap) + 30 (hidden-dep cap) = 100 -> floored at 0, not negative.
    assert result["score"] == pytest.approx(0.0)


def test_high_risk_ratio_excludes_deleted_files_from_the_denominator(db_session):
    """Part C: RiskEngine never scores deleted files (they get no
    FileMetrics row), so _high_risk_ratio's denominator must be scoped the
    same way -- otherwise a repo with real deletion history understates the
    ratio. Fixture: 60 deleted files (never scored) + 4 live files, 3 of
    them high-risk. The old, buggy behaviour would compute 3/64; the correct
    behaviour is 3/4.
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-deleted-files")
    run_id = _make_run(db_session, repo_id)

    for i in range(60):
        _add_deleted_file(db_session, repo_id, f"gone{i}.py")

    _add_file_with_risk_score(db_session, repo_id, run_id, "hot1.py", risk_score=0.9)
    _add_file_with_risk_score(db_session, repo_id, run_id, "hot2.py", risk_score=0.8)
    _add_file_with_risk_score(db_session, repo_id, run_id, "hot3.py", risk_score=0.7)
    _add_file_with_risk_score(db_session, repo_id, run_id, "ok1.py", risk_score=0.1)
    db_session.commit()

    result = HealthEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    # 3 of 4 LIVE files are high-risk, not 3 of 64 total-ever files.
    assert result["high_risk_ratio"] == pytest.approx(0.75)
