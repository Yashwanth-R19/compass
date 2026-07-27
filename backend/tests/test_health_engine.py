import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from app.db.models import Coupling, Dependency, File, FileMetrics, Repo, RepoPath, RepoStatus
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


def _add_file_with_risk_score(db_session, repo_id: uuid.UUID, path: str, risk_score: float) -> None:
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
        FileMetrics(file_id=file.id, risk_score=risk_score, risk_confidence=0.5, hotspot_rank=0)
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


def _add_coupling(db_session, repo_id: uuid.UUID, path_a: str, path_b: str) -> None:
    path_ids = _intern_paths(db_session, repo_id, [path_a, path_b])
    db_session.execute(
        insert(Coupling),
        [
            {
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
    for i in range(4):
        _add_file_with_risk_score(db_session, repo_id, f"f{i}.py", risk_score=0.1)
    db_session.commit()

    result = HealthEngine().run(repo_id, db_session)
    db_session.commit()

    assert result["score"] == pytest.approx(100.0)
    assert result["high_risk_ratio"] == pytest.approx(0.0)
    assert result["cycle_count"] == 0
    assert result["hidden_dependency_count"] == 0


def test_penalties_apply_and_are_uncapped_below_threshold(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-penalized")
    # 2 of 4 files are high-risk (>= 0.60) -> high_risk_ratio = 0.5
    _add_file_with_risk_score(db_session, repo_id, "hot1.py", risk_score=0.8)
    _add_file_with_risk_score(db_session, repo_id, "hot2.py", risk_score=0.7)
    _add_file_with_risk_score(db_session, repo_id, "ok1.py", risk_score=0.2)
    _add_file_with_risk_score(db_session, repo_id, "ok2.py", risk_score=0.3)

    # One 2-file cycle: x.py <-> y.py
    _add_dependency(db_session, repo_id, "x.py", "y.py")
    _add_dependency(db_session, repo_id, "y.py", "x.py")

    # One hidden dependency: m.py/n.py coupled, no structural edge between them.
    _add_coupling(db_session, repo_id, "m.py", "n.py")
    db_session.commit()

    result = HealthEngine().run(repo_id, db_session)
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
    # All files high-risk -> high_risk_ratio = 1.0 -> risk_penalty = 40 (uncapped, <=100)
    for i in range(3):
        _add_file_with_risk_score(db_session, repo_id, f"hot{i}.py", risk_score=0.9)
    db_session.commit()

    # Many small planted cycles so CYCLE_PENALTY_PER_CYCLE * count exceeds the cap.
    cycles_needed = int(CYCLE_PENALTY_CAP // CYCLE_PENALTY_PER_CYCLE) + 3
    for i in range(cycles_needed):
        _add_dependency(db_session, repo_id, f"p{i}.py", f"q{i}.py")
        _add_dependency(db_session, repo_id, f"q{i}.py", f"p{i}.py")

    # Many hidden-dependency pairs so their penalty also exceeds its cap.
    pairs_needed = int(HIDDEN_DEP_PENALTY_CAP // HIDDEN_DEP_PENALTY_PER_PAIR) + 3
    for i in range(pairs_needed):
        _add_coupling(db_session, repo_id, f"m{i}.py", f"n{i}.py")
    db_session.commit()

    result = HealthEngine().run(repo_id, db_session)
    db_session.commit()

    assert result["cycle_count"] == cycles_needed
    assert result["hidden_dependency_count"] == pairs_needed
    # 40 (risk) + 30 (cycle cap) + 30 (hidden-dep cap) = 100 -> floored at 0, not negative.
    assert result["score"] == pytest.approx(0.0)
