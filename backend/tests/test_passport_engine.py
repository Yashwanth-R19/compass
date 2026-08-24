import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select

from app.baseline.base import BaselineProvider
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    Contributor,
    File,
    Health,
    Repo,
    RepoManifest,
    RepoPassport,
    RepoPath,
    RepoStatus,
    Subsystem,
    TruckFactor,
)
from app.engines.context import RunContext
from app.engines.passport import PassportEngine, compute_passport


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


def _add_file(
    db_session, repo_id: uuid.UUID, path: str, *, complexity: float = 1.0, churn_total: int = 1
) -> int:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path=path,
            language="python",
            current_loc=10,
            complexity=complexity,
            churn_total=churn_total,
            commit_count=1,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
        )
    )
    db_session.flush()
    return path_id


def _add_commit(db_session, repo_id: uuid.UUID, sha: str, when: datetime) -> None:
    db_session.add(
        Commit(
            repo_id=repo_id,
            sha=sha,
            author_name="tester",
            author_email="tester@example.com",
            committed_at=when,
            message="synthetic",
            is_fix=False,
            is_revert=False,
            files_changed=1,
            insertions=1,
            deletions=0,
            changed_path_ids=[],
            added_lines=[],
            deleted_lines=[],
        )
    )


def _add_contributor(
    db_session,
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    name: str,
    commit_count: int,
    rank: int,
    is_stale: bool = False,
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        Contributor(
            analysis_run_id=run_id,
            repo_id=repo_id,
            canonical_name=name,
            canonical_email=f"{name.lower()}@example.com",
            aliases=[{"name": name, "email": f"{name.lower()}@example.com"}],
            commit_count=commit_count,
            lines_added=0,
            lines_deleted=0,
            first_commit_at=now,
            last_commit_at=now,
            is_bot=False,
            active_days=1,
            is_stale=is_stale,
            rank=rank,
        )
    )


def _add_truck_factor(db_session, repo_id: uuid.UUID, run_id: uuid.UUID, value: int) -> None:
    db_session.add(
        TruckFactor(
            id=uuid.uuid4(),
            analysis_run_id=run_id,
            repo_id=repo_id,
            value=value,
            removal_order=[],
            total_files_considered=1,
            orphaned_file_count=0,
            note=None,
        )
    )


def _add_subsystem(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, label: str, rank: int, cohesion: float = 0.8
) -> None:
    db_session.execute(
        insert(Subsystem).values(
            analysis_run_id=run_id,
            repo_id=repo_id,
            label=label,
            label_source="fallback",
            file_count=1,
            total_loc=10,
            internal_edges=0,
            external_edges=0,
            cohesion=cohesion,
            rank=rank,
        )
    )


def _add_health(
    db_session,
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    score: float = 90.0,
    high_risk_ratio: float = 0.0,
    cycle_count: int = 0,
    hidden_dependency_count: int = 0,
) -> None:
    db_session.add(
        Health(
            id=uuid.uuid4(),
            analysis_run_id=run_id,
            repo_id=repo_id,
            score=score,
            high_risk_ratio=high_risk_ratio,
            cycle_count=cycle_count,
            hidden_dependency_count=hidden_dependency_count,
        )
    )


def _add_readme(db_session, repo_id: uuid.UUID, *, line_count: int = 20) -> None:
    path_id = _intern_paths(db_session, repo_id, ["README.md"])["README.md"]
    db_session.execute(
        insert(RepoManifest),
        [
            {
                "repo_id": repo_id,
                "path_id": path_id,
                "kind": "readme",
                "data": {"heading": "x", "line_count": line_count},
            }
        ],
    )


class _RecordingBaseline(BaselineProvider):
    """Records every ``risk_normalizer`` call and always returns a constant
    normalized value, regardless of input -- proves PassportEngine actually
    calls through the injected provider rather than hardcoding the maths
    (session 06 Part F's explicit requirement)."""

    def __init__(self, constant: float = 0.42) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._constant = constant

    def percentile(self, metric: str, language: str, size_bucket: str, value: float) -> float:
        raise NotImplementedError

    def risk_normalizer(
        self, metric: str, language: str, size_bucket: str
    ) -> Callable[[Sequence[float]], list[float]]:
        self.calls.append((metric, language, size_bucket))
        constant = self._constant
        return lambda values: [constant for _ in values]


def test_one_file_one_commit_repo_produces_valid_passport_with_no_crash(db_session):
    """Session 06 Known Hazard #2: this test exists specifically to catch
    division-by-zero bugs (churn_concentration, subsystem_spread/total,
    truck_factor/4, median of a singleton list) -- see the module
    docstring's own "guarded at every one of these sites" list."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-one-file")
    _add_file(db_session, repo_id, "only.py", complexity=2.0, churn_total=5)
    now = datetime.now(UTC)
    _add_commit(db_session, repo_id, "c1", now)
    run_id = _make_run(db_session, repo_id)
    _add_contributor(db_session, repo_id, run_id, name="Solo Dev", commit_count=1, rank=0)
    _add_truck_factor(db_session, repo_id, run_id, 1)
    _add_subsystem(db_session, repo_id, run_id, "Unclustered", 0)
    _add_health(db_session, repo_id, run_id)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    data, difficulty, breakdown = compute_passport(
        repo_id, run_id, db_session, ctx, _RecordingBaseline()
    )

    assert data.scale.files == 1
    assert data.scale.commits == 1
    assert data.scale.contributors == 1
    assert data.scale.subsystems == 1
    assert data.scale.age_days == 0.0
    assert data.hotspots.churn_concentration == pytest.approx(1.0)
    assert data.team.truck_factor == 1
    assert 0.0 <= difficulty <= 100.0
    assert breakdown["truck_factor"]["normalized"] == pytest.approx(0.75)  # 1 - min(1, 1/4)


def test_norm_comes_from_the_injected_baseline_provider(db_session):
    """The explicit stub-injection proof: assert the provider was actually
    called (3 times, once per norm()-wrapped term) and that the returned
    difficulty is hand-computable purely from the stub's constant output
    plus the two non-normalized terms (doc_coverage, truck_factor)."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-baseline-stub")
    _add_file(db_session, repo_id, "a.py")
    _add_file(db_session, repo_id, "b.py")
    now = datetime.now(UTC)
    _add_commit(db_session, repo_id, "c1", now)
    run_id = _make_run(db_session, repo_id)
    _add_contributor(db_session, repo_id, run_id, name="Dev", commit_count=1, rank=0)
    _add_truck_factor(
        db_session, repo_id, run_id, 2
    )  # truck_factor_component = 1 - min(1, 2/4) = 0.5
    _add_subsystem(db_session, repo_id, run_id, "sub-a", 0)
    _add_subsystem(db_session, repo_id, run_id, "sub-b", 1)
    _add_readme(
        db_session, repo_id, line_count=20
    )  # has_readme -> +0.5, <=100 lines -> +0, no docs/ -> +0
    _add_health(db_session, repo_id, run_id)
    db_session.commit()

    stub = _RecordingBaseline(constant=0.42)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    data, difficulty, breakdown = compute_passport(repo_id, run_id, db_session, ctx, stub)

    assert len(stub.calls) == 3
    assert {metric for metric, _lang, _bucket in stub.calls} == {
        "subsystem_count",
        "median_file_complexity",
        "max_dependency_depth",
    }

    # doc_coverage = 0.5 (readme only) -> component 0.5; truck_factor
    # component 0.5 (see above); the other three terms are the stub's fixed
    # 0.42, weighted 0.25/0.20/0.15.
    expected = 100.0 * (0.42 * (0.25 + 0.20 + 0.15) + 0.5 * (0.20 + 0.20))
    assert difficulty == pytest.approx(expected)
    assert breakdown["doc_coverage"]["normalized"] == pytest.approx(0.5)
    assert breakdown["truck_factor"]["normalized"] == pytest.approx(0.5)
    assert data.identity.has_readme is True


def test_difficulty_score_is_reproducible(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-reproducible")
    _add_file(db_session, repo_id, "a.py", complexity=3.0)
    _add_file(db_session, repo_id, "b.py", complexity=5.0)
    now = datetime.now(UTC)
    _add_commit(db_session, repo_id, "c1", now)
    _add_commit(db_session, repo_id, "c2", now - timedelta(days=10))
    run_id = _make_run(db_session, repo_id)
    _add_contributor(db_session, repo_id, run_id, name="Dev", commit_count=2, rank=0)
    _add_truck_factor(db_session, repo_id, run_id, 3)
    _add_subsystem(db_session, repo_id, run_id, "sub-a", 0)
    _add_health(db_session, repo_id, run_id)
    db_session.commit()

    ctx1 = RunContext(repo_id=repo_id, run_id=run_id)
    data1, difficulty1, breakdown1 = compute_passport(
        repo_id, run_id, db_session, ctx1, _RecordingBaseline()
    )
    ctx2 = RunContext(repo_id=repo_id, run_id=run_id)
    data2, difficulty2, breakdown2 = compute_passport(
        repo_id, run_id, db_session, ctx2, _RecordingBaseline()
    )

    assert difficulty1 == pytest.approx(difficulty2)
    assert breakdown1 == breakdown2
    assert data1.model_dump() == data2.model_dump()


def test_no_readme_drags_difficulty_up_via_doc_coverage(db_session):
    def _build(url: str, *, with_readme: bool) -> tuple[uuid.UUID, uuid.UUID]:
        repo_id = _make_repo(db_session, url)
        _add_file(db_session, repo_id, "a.py")
        now = datetime.now(UTC)
        _add_commit(db_session, repo_id, "c1", now)
        run_id = _make_run(db_session, repo_id)
        _add_contributor(db_session, repo_id, run_id, name="Dev", commit_count=1, rank=0)
        _add_truck_factor(db_session, repo_id, run_id, 3)
        _add_subsystem(db_session, repo_id, run_id, "sub-a", 0)
        if with_readme:
            _add_readme(db_session, repo_id, line_count=20)
        _add_health(db_session, repo_id, run_id)
        db_session.commit()
        return repo_id, run_id

    repo_with, run_with = _build("https://github.com/fixture/passport-doc-with", with_readme=True)
    repo_without, run_without = _build(
        "https://github.com/fixture/passport-doc-without", with_readme=False
    )

    stub = _RecordingBaseline(constant=0.42)
    data_with, difficulty_with, breakdown_with = compute_passport(
        repo_with, run_with, db_session, RunContext(repo_id=repo_with, run_id=run_with), stub
    )
    data_without, difficulty_without, breakdown_without = compute_passport(
        repo_without,
        run_without,
        db_session,
        RunContext(repo_id=repo_without, run_id=run_without),
        stub,
    )

    assert data_with.identity.has_readme is True
    assert data_without.identity.has_readme is False
    assert breakdown_with["doc_coverage"]["normalized"] == pytest.approx(0.5)
    assert breakdown_without["doc_coverage"]["normalized"] == pytest.approx(1.0)
    # 0.20 weight * (1.0 - 0.5) difference in doc_coverage component, times 100.
    assert (difficulty_without - difficulty_with) == pytest.approx(10.0)
    assert difficulty_without > difficulty_with


def test_churn_concentration_hand_computed(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-churn")
    _add_file(db_session, repo_id, "hot.py", churn_total=100)
    for i in range(9):
        _add_file(db_session, repo_id, f"f{i}.py", churn_total=1)
    now = datetime.now(UTC)
    _add_commit(db_session, repo_id, "c1", now)
    run_id = _make_run(db_session, repo_id)
    _add_contributor(db_session, repo_id, run_id, name="Dev", commit_count=1, rank=0)
    _add_truck_factor(db_session, repo_id, run_id, 1)
    _add_subsystem(db_session, repo_id, run_id, "sub-a", 0)
    _add_health(db_session, repo_id, run_id)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    data, _difficulty, _breakdown = compute_passport(
        repo_id, run_id, db_session, ctx, _RecordingBaseline()
    )

    # top ceil(0.1 * 10) = 1 file (churn 100) out of total churn 109.
    assert data.hotspots.churn_concentration == pytest.approx(100 / 109)


def test_first_pr_rules_fire_in_priority_order_capped_at_three(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-first-pr")
    _add_file(db_session, repo_id, "hot.py", churn_total=100)
    for i in range(9):
        _add_file(db_session, repo_id, f"f{i}.py", churn_total=1)
    now = datetime.now(UTC)
    _add_commit(db_session, repo_id, "c1", now)
    run_id = _make_run(db_session, repo_id)
    _add_contributor(db_session, repo_id, run_id, name="Dev", commit_count=1, rank=0)
    _add_truck_factor(db_session, repo_id, run_id, 1)  # <= 2 -> LOW_TRUCK_FACTOR fires
    _add_subsystem(db_session, repo_id, run_id, "sub-a", 0)
    _add_health(db_session, repo_id, run_id, hidden_dependency_count=3, cycle_count=2)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    data, _difficulty, _breakdown = compute_passport(
        repo_id, run_id, db_session, ctx, _RecordingBaseline()
    )

    codes = [item.code for item in data.first_pr]
    assert len(codes) == 3
    # HIGH_CHURN_CONCENTRATION (churn 100/109 > 0.5) and LOW_TRUCK_FACTOR
    # (1 <= 2) both fire and outrank everything else; ORPHANED_HOTSPOT does
    # not fire (no file_expertise data at all in this fixture), so the
    # third slot goes to the next rule that DOES fire: HIDDEN_DEPENDENCIES.
    assert codes == ["HIGH_CHURN_CONCENTRATION", "LOW_TRUCK_FACTOR", "HIDDEN_DEPENDENCIES"]


def test_engine_persists_data_matching_compute_passport(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-engine-persist")
    _add_file(db_session, repo_id, "a.py")
    now = datetime.now(UTC)
    _add_commit(db_session, repo_id, "c1", now)
    run_id = _make_run(db_session, repo_id)
    _add_contributor(db_session, repo_id, run_id, name="Dev", commit_count=1, rank=0)
    _add_truck_factor(db_session, repo_id, run_id, 1)
    _add_subsystem(db_session, repo_id, run_id, "sub-a", 0)
    _add_health(db_session, repo_id, run_id)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    metadata = PassportEngine().run(ctx, db_session)
    db_session.commit()

    row = db_session.scalar(select(RepoPassport).where(RepoPassport.analysis_run_id == run_id))
    assert row is not None
    assert row.onboarding_difficulty == pytest.approx(metadata["onboarding_difficulty"])
    assert row.data["scale"]["files"] == 1
    assert "first_pr" in row.data
