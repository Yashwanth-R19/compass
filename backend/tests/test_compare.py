import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import insert, select

from app.analysis.compare import compare_runs, subsystem_changes
from app.api.compare import get_compare
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Contributor,
    FileMetrics,
    Finding,
    Health,
    Repo,
    RepoPath,
    RepoStatus,
    Severity,
    User,
)


def _make_repo(db_session, url: str, **kwargs) -> Repo:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.ready, **kwargs)
    db_session.add(repo)
    db_session.flush()
    return repo


def _make_run(
    db_session, repo_id: uuid.UUID, *, started_at: datetime, engine_version: int = 2
) -> AnalysisRun:
    run = AnalysisRun(
        repo_id=repo_id,
        status=AnalysisRunStatus.ready,
        head_sha=f"sha-{uuid.uuid4().hex[:8]}",
        started_at=started_at,
        engine_version=engine_version,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _intern_path(db_session, repo_id: uuid.UUID, path: str) -> int:
    existing = db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == path)
    )
    if existing is not None:
        return existing
    db_session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": path}])
    db_session.flush()
    return db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == path)
    )


def _add_finding(
    db_session,
    run_id: uuid.UUID,
    repo_id: uuid.UUID,
    *,
    signature: str,
    category: str = "risk",
    path_id=None,
) -> None:
    db_session.add(
        Finding(
            analysis_run_id=run_id,
            repo_id=repo_id,
            category=category,
            severity=Severity.high,
            confidence=0.8,
            path_id=path_id,
            title=f"finding {signature}",
            detail="synthetic",
            rank=0,
            signature=signature,
        )
    )


# --- Findings diff: resolved / appeared / persisted -------------------------


def test_findings_diff_classifies_resolved_appeared_persisted(db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/compare-findings")
    run_before = _make_run(db_session, repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_after = _make_run(db_session, repo.id, started_at=datetime(2024, 2, 1, tzinfo=UTC))

    _add_finding(db_session, run_before.id, repo.id, signature="sig-resolved")
    _add_finding(db_session, run_before.id, repo.id, signature="sig-persisted")
    _add_finding(db_session, run_after.id, repo.id, signature="sig-persisted")
    _add_finding(db_session, run_after.id, repo.id, signature="sig-appeared")
    db_session.commit()

    result = compare_runs(db_session, run_before, run_after)

    appeared_sigs = {f.signature for f in result.findings.appeared}
    resolved_sigs = {f.signature for f in result.findings.resolved}
    persisted_sigs = {f.signature for f in result.findings.persisted}

    assert appeared_sigs == {"sig-appeared"}
    assert resolved_sigs == {"sig-resolved"}
    assert persisted_sigs == {"sig-persisted"}
    assert result.findings.appeared_total == 1
    assert result.findings.resolved_total == 1
    assert result.findings.persisted_total == 1


def test_compare_runs_orders_before_after_by_started_at_regardless_of_call_order(db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/compare-order")
    earlier = _make_run(db_session, repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    later = _make_run(db_session, repo.id, started_at=datetime(2024, 3, 1, tzinfo=UTC))
    db_session.commit()

    forward = compare_runs(db_session, earlier, later)
    backward = compare_runs(db_session, later, earlier)

    assert forward.run_before == earlier.id
    assert forward.run_after == later.id
    assert backward.run_before == earlier.id
    assert backward.run_after == later.id


def test_engine_version_differs_flag(db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/compare-engine-version")
    run_before = _make_run(
        db_session, repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC), engine_version=1
    )
    run_after = _make_run(
        db_session, repo.id, started_at=datetime(2024, 2, 1, tzinfo=UTC), engine_version=2
    )
    db_session.commit()

    result = compare_runs(db_session, run_before, run_after)
    assert result.engine_version_differs is True
    assert result.engine_version_before == 1
    assert result.engine_version_after == 2


def test_headline_deltas_reflect_health_and_truck_factor(db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/compare-headline")
    run_before = _make_run(db_session, repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_after = _make_run(db_session, repo.id, started_at=datetime(2024, 2, 1, tzinfo=UTC))
    db_session.add(
        Health(
            analysis_run_id=run_before.id,
            repo_id=repo.id,
            score=60.0,
            high_risk_ratio=0.3,
            cycle_count=1,
            hidden_dependency_count=2,
        )
    )
    db_session.add(
        Health(
            analysis_run_id=run_after.id,
            repo_id=repo.id,
            score=75.0,
            high_risk_ratio=0.2,
            cycle_count=0,
            hidden_dependency_count=1,
        )
    )
    db_session.commit()

    result = compare_runs(db_session, run_before, run_after)
    health_delta = next(h for h in result.headline if h.metric == "health_score")
    assert health_delta.before == 60.0
    assert health_delta.after == 75.0
    assert health_delta.delta == 15.0
    assert health_delta.higher_is_better is True

    hidden_dep_delta = next(h for h in result.headline if h.metric == "hidden_dependency_count")
    assert hidden_dep_delta.delta == -1.0
    assert hidden_dep_delta.higher_is_better is False


def test_risk_movers_split_by_direction(db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/compare-risk-movers")
    run_before = _make_run(db_session, repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_after = _make_run(db_session, repo.id, started_at=datetime(2024, 2, 1, tzinfo=UTC))
    worsened_path = _intern_path(db_session, repo.id, "src/worsened.py")
    improved_path = _intern_path(db_session, repo.id, "src/improved.py")
    db_session.execute(
        insert(FileMetrics),
        [
            {
                "analysis_run_id": run_before.id,
                "repo_id": repo.id,
                "path_id": worsened_path,
                "risk_score": 0.2,
                "hotspot_rank": 5,
            },
            {
                "analysis_run_id": run_after.id,
                "repo_id": repo.id,
                "path_id": worsened_path,
                "risk_score": 0.9,
                "hotspot_rank": 0,
            },
            {
                "analysis_run_id": run_before.id,
                "repo_id": repo.id,
                "path_id": improved_path,
                "risk_score": 0.9,
                "hotspot_rank": 0,
            },
            {
                "analysis_run_id": run_after.id,
                "repo_id": repo.id,
                "path_id": improved_path,
                "risk_score": 0.1,
                "hotspot_rank": 8,
            },
        ],
    )
    db_session.commit()

    result = compare_runs(db_session, run_before, run_after)
    assert [m.file_path for m in result.risk_movers_worsened] == ["src/worsened.py"]
    assert [m.file_path for m in result.risk_movers_improved] == ["src/improved.py"]
    assert result.risk_movers_worsened[0].rank_delta == 5  # rank 5 -> 0, moved toward worse
    assert result.risk_movers_improved[0].rank_delta == -8  # rank 0 -> 8, moved toward better


def test_contributor_joined_left_went_stale(db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/compare-contributors")
    run_before = _make_run(db_session, repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_after = _make_run(db_session, repo.id, started_at=datetime(2024, 2, 1, tzinfo=UTC))
    now = datetime(2024, 1, 1, tzinfo=UTC)

    def _contributor(run_id, email, name, *, is_stale=False):
        return Contributor(
            analysis_run_id=run_id,
            repo_id=repo.id,
            canonical_name=name,
            canonical_email=email,
            aliases=[{"name": name, "email": email}],
            commit_count=5,
            lines_added=10,
            lines_deleted=2,
            first_commit_at=now,
            last_commit_at=now,
            is_bot=False,
            active_days=3,
            is_stale=is_stale,
            rank=0,
        )

    db_session.add(_contributor(run_before.id, "alice@example.com", "Alice"))
    db_session.add(_contributor(run_before.id, "carol@example.com", "Carol", is_stale=False))
    db_session.add(_contributor(run_after.id, "carol@example.com", "Carol", is_stale=True))
    db_session.add(_contributor(run_after.id, "dave@example.com", "Dave"))
    db_session.commit()

    result = compare_runs(db_session, run_before, run_after)
    kinds_by_name = {c.name: c.kind for c in result.contributor_changes}
    assert kinds_by_name["Alice"] == "left"
    assert kinds_by_name["Carol"] == "went_stale"
    assert kinds_by_name["Dave"] == "joined"


# --- Subsystem Jaccard matching (pure, no DB) --------------------------------


def _subsystem(label: str, members: set[int], file_count: int | None = None) -> dict:
    return {"label": label, "members": members, "file_count": file_count or len(members)}


def test_subsystem_that_gained_two_files_still_matches():
    before = {1: _subsystem("billing", {1, 2, 3, 4, 5, 6, 7, 8})}
    after = {10: _subsystem("billing", {1, 2, 3, 4, 5, 6, 7, 8, 9, 10})}
    changes = subsystem_changes(before, after)
    # Jaccard = 8 / 10 = 0.8 >= 0.5 -- treated as the same subsystem, persisted.
    assert changes == []


def test_subsystem_sharing_20_percent_of_members_does_not_match():
    before = {1: _subsystem("billing", set(range(10)))}
    after = {10: _subsystem("payments", set(range(8, 18)))}  # overlap = {8, 9} -> 2/18 =~ 0.11
    changes = subsystem_changes(before, after)
    kinds = {c.kind for c in changes}
    assert "disappeared" in kinds
    assert "appeared" in kinds


def test_subsystem_split_and_merge():
    # One before-subsystem's members are matched by TWO after-subsystems -> split.
    before = {1: _subsystem("monolith", {1, 2, 3, 4})}
    after = {
        10: _subsystem("billing", {1, 2, 3}),
        11: _subsystem("shipping", {2, 3, 4}),
    }
    changes = subsystem_changes(before, after)
    assert any(c.kind == "split" and c.label == "monolith" for c in changes)

    # Two before-subsystems both best-match the SAME after-subsystem -> merge.
    before2 = {
        1: _subsystem("billing", {1, 2, 3}),
        2: _subsystem("shipping", {2, 3, 4}),
    }
    after2 = {10: _subsystem("commerce", {1, 2, 3, 4})}
    changes2 = subsystem_changes(before2, after2)
    assert any(c.kind == "merged" and c.label == "commerce" for c in changes2)


# --- Access control -----------------------------------------------------------


def _make_user(db_session, github_id: int) -> User:
    user = User(github_id=github_id, github_login=f"user-{github_id}")
    db_session.add(user)
    db_session.flush()
    return user


def test_compare_requires_access_to_both_runs_a_unreadable(db_session):
    owner = _make_user(db_session, 101)
    public_repo = _make_repo(db_session, "https://github.com/fixture/compare-public-a")
    private_repo = _make_repo(
        db_session,
        "https://github.com/fixture/compare-private-a",
        is_private=True,
        owner_user_id=owner.id,
    )
    run_public = _make_run(db_session, public_repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_private = _make_run(
        db_session, private_repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC)
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_compare(a=run_private.id, b=run_public.id, db=db_session, user=None)
    assert exc_info.value.status_code == 403


def test_compare_requires_access_to_both_runs_b_unreadable(db_session):
    owner = _make_user(db_session, 102)
    public_repo = _make_repo(db_session, "https://github.com/fixture/compare-public-b")
    private_repo = _make_repo(
        db_session,
        "https://github.com/fixture/compare-private-b",
        is_private=True,
        owner_user_id=owner.id,
    )
    run_public = _make_run(db_session, public_repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_private = _make_run(
        db_session, private_repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC)
    )
    db_session.commit()

    # The asymmetric case: `a` (public) is readable, `b` (private) is not --
    # this must still 403, not silently compare using only the readable side.
    with pytest.raises(HTTPException) as exc_info:
        get_compare(a=run_public.id, b=run_private.id, db=db_session, user=None)
    assert exc_info.value.status_code == 403


def test_compare_owner_can_read_own_private_run_pair(db_session):
    owner = _make_user(db_session, 103)
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/compare-owner",
        is_private=True,
        owner_user_id=owner.id,
    )
    run_a = _make_run(db_session, repo.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_b = _make_run(db_session, repo.id, started_at=datetime(2024, 2, 1, tzinfo=UTC))
    db_session.commit()

    result = get_compare(a=run_a.id, b=run_b.id, db=db_session, user=owner)
    assert result.repo_id == repo.id


def test_compare_runs_raises_for_different_repos(db_session):
    repo_a = _make_repo(db_session, "https://github.com/fixture/compare-diff-a")
    repo_b = _make_repo(db_session, "https://github.com/fixture/compare-diff-b")
    run_a = _make_run(db_session, repo_a.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    run_b = _make_run(db_session, repo_b.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
    db_session.commit()

    with pytest.raises(ValueError):
        compare_runs(db_session, run_a, run_b)
