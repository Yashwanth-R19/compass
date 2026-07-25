import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert

from app.db.base import SessionLocal
from app.db.models import Coupling, Dependency, File, FileMetrics, Repo, RepoStatus
from app.db.wipe import wipe_repo_data
from app.engines.health import (
    CYCLE_PENALTY_CAP,
    CYCLE_PENALTY_PER_CYCLE,
    HIDDEN_DEP_PENALTY_CAP,
    HIDDEN_DEP_PENALTY_PER_PAIR,
    RISK_PENALTY_WEIGHT,
    HealthEngine,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def _add_file_with_risk_score(db_session, repo_id: uuid.UUID, path: str, risk_score: float) -> None:
    now = datetime.now(timezone.utc)
    file = File(
        repo_id=repo_id,
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
    db_session.add(FileMetrics(file_id=file.id, risk_score=risk_score, risk_confidence=0.5, hotspot_rank=0))


def _cleanup_repo(db_session, repo_id: uuid.UUID) -> None:
    wipe_repo_data(repo_id, db_session)
    db_session.query(Repo).filter(Repo.id == repo_id).delete()
    db_session.commit()


def test_healthy_repo_scores_100(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-perfect")
    try:
        for i in range(4):
            _add_file_with_risk_score(db_session, repo_id, f"f{i}.py", risk_score=0.1)
        db_session.commit()

        result = HealthEngine().run(repo_id, db_session)
        db_session.commit()

        assert result["score"] == pytest.approx(100.0)
        assert result["high_risk_ratio"] == pytest.approx(0.0)
        assert result["cycle_count"] == 0
        assert result["hidden_dependency_count"] == 0
    finally:
        _cleanup_repo(db_session, repo_id)


def test_penalties_apply_and_are_uncapped_below_threshold(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-penalized")
    try:
        # 2 of 4 files are high-risk (>= 0.60) -> high_risk_ratio = 0.5
        _add_file_with_risk_score(db_session, repo_id, "hot1.py", risk_score=0.8)
        _add_file_with_risk_score(db_session, repo_id, "hot2.py", risk_score=0.7)
        _add_file_with_risk_score(db_session, repo_id, "ok1.py", risk_score=0.2)
        _add_file_with_risk_score(db_session, repo_id, "ok2.py", risk_score=0.3)

        # One 2-file cycle: x.py <-> y.py
        db_session.execute(
            insert(Dependency),
            [
                {"id": uuid.uuid4(), "repo_id": repo_id, "from_path": "x.py", "to_path": "y.py", "dep_type": "import"},
                {"id": uuid.uuid4(), "repo_id": repo_id, "from_path": "y.py", "to_path": "x.py", "dep_type": "import"},
            ],
        )

        # One hidden dependency: m.py/n.py coupled, no structural edge between them.
        db_session.execute(
            insert(Coupling),
            [
                {
                    "id": uuid.uuid4(),
                    "repo_id": repo_id,
                    "file_a_path": "m.py",
                    "file_b_path": "n.py",
                    "shared_revs": 6,
                    "coupling_degree": 0.9,
                    "avg_revs": 6.0,
                }
            ],
        )
        db_session.commit()

        result = HealthEngine().run(repo_id, db_session)
        db_session.commit()

        assert result["high_risk_ratio"] == pytest.approx(0.5)
        assert result["cycle_count"] == 1
        assert result["hidden_dependency_count"] == 1

        expected_score = 100.0 - (RISK_PENALTY_WEIGHT * 0.5) - CYCLE_PENALTY_PER_CYCLE - HIDDEN_DEP_PENALTY_PER_PAIR
        assert result["score"] == pytest.approx(expected_score)
    finally:
        _cleanup_repo(db_session, repo_id)


def test_penalties_are_capped_and_score_floors_at_zero(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/health-floor")
    try:
        # All files high-risk -> high_risk_ratio = 1.0 -> risk_penalty = 40 (uncapped, <=100)
        for i in range(3):
            _add_file_with_risk_score(db_session, repo_id, f"hot{i}.py", risk_score=0.9)
        db_session.commit()

        # Many small planted cycles so CYCLE_PENALTY_PER_CYCLE * count exceeds the cap.
        cycles_needed = int(CYCLE_PENALTY_CAP // CYCLE_PENALTY_PER_CYCLE) + 3
        dep_rows = []
        for i in range(cycles_needed):
            dep_rows.append(
                {"id": uuid.uuid4(), "repo_id": repo_id, "from_path": f"p{i}.py", "to_path": f"q{i}.py", "dep_type": "import"}
            )
            dep_rows.append(
                {"id": uuid.uuid4(), "repo_id": repo_id, "from_path": f"q{i}.py", "to_path": f"p{i}.py", "dep_type": "import"}
            )
        db_session.execute(insert(Dependency), dep_rows)

        # Many hidden-dependency pairs so their penalty also exceeds its cap.
        pairs_needed = int(HIDDEN_DEP_PENALTY_CAP // HIDDEN_DEP_PENALTY_PER_PAIR) + 3
        coupling_rows = [
            {
                "id": uuid.uuid4(),
                "repo_id": repo_id,
                "file_a_path": f"m{i}.py",
                "file_b_path": f"n{i}.py",
                "shared_revs": 6,
                "coupling_degree": 0.9,
                "avg_revs": 6.0,
            }
            for i in range(pairs_needed)
        ]
        db_session.execute(insert(Coupling), coupling_rows)
        db_session.commit()

        result = HealthEngine().run(repo_id, db_session)
        db_session.commit()

        assert result["cycle_count"] == cycles_needed
        assert result["hidden_dependency_count"] == pairs_needed
        # 40 (risk) + 30 (cycle cap) + 30 (hidden-dep cap) = 100 -> floored at 0, not negative.
        assert result["score"] == pytest.approx(0.0)
    finally:
        _cleanup_repo(db_session, repo_id)
