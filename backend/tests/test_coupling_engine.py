import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    Coupling,
    Repo,
    RepoPath,
    RepoStatus,
)
from app.engines.coupling import (
    FALLBACK_MIN_SHARED_REVS,
    MIN_SHARED_REVS,
    CouplingEngine,
    confidence_hint,
    is_low_confidence,
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
    """Path-string -> repo_paths.id map, inserting any paths not already
    interned for ``repo_id``. Bypasses persist.py entirely -- CouplingEngine
    is pure over commits.changed_path_ids, so it doesn't care how those ids
    got assigned."""
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


def _add_commit(
    db_session, repo_id: uuid.UUID, sha: str, file_paths: list[str], when: datetime
) -> None:
    path_ids = _intern_paths(db_session, repo_id, file_paths)
    commit = Commit(
        repo_id=repo_id,
        sha=sha,
        author_name="tester",
        author_email="tester@example.com",
        committed_at=when,
        message="synthetic",
        is_fix=False,
        is_revert=False,
        files_changed=len(file_paths),
        insertions=0,
        deletions=0,
        changed_path_ids=[path_ids[p] for p in file_paths],
        added_lines=[0 for _ in file_paths],
        deleted_lines=[0 for _ in file_paths],
    )
    db_session.add(commit)
    db_session.flush()


def _path_by_id(db_session, repo_id: uuid.UUID) -> dict[int, str]:
    return {
        row.id: row.path
        for row in db_session.execute(
            select(RepoPath.id, RepoPath.path).where(RepoPath.repo_id == repo_id)
        ).all()
    }


def test_coupled_files_detected_and_uncoupled_file_excluded(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/coupling-basic")
    now = datetime.now(UTC)
    # A and B always change together -- enough times to clear both
    # MIN_SHARED_REVS and MIN_COUPLING_DEGREE.
    for i in range(6):
        _add_commit(db_session, repo_id, f"ab{i}", ["a.py", "b.py"], now)
    # C changes on its own every time -- never co-occurs with anything.
    for i in range(6):
        _add_commit(db_session, repo_id, f"c{i}", ["c.py"], now)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = CouplingEngine().run(repo_id, run_id, db_session)
    db_session.commit()

    assert metadata["low_confidence"] is False
    assert metadata["commits_analyzed"] == 12

    rows = db_session.scalars(select(Coupling).where(Coupling.repo_id == repo_id)).all()
    path_by_id = _path_by_id(db_session, repo_id)

    assert not any("c.py" in (path_by_id[r.path_a_id], path_by_id[r.path_b_id]) for r in rows)

    ab = next(
        r for r in rows if {path_by_id[r.path_a_id], path_by_id[r.path_b_id]} == {"a.py", "b.py"}
    )
    assert ab.shared_revs == 6
    # revs(a) == revs(b) == 6 -> coupling_degree = 6 / min(6, 6) = 1.0
    assert ab.coupling_degree == pytest.approx(1.0)
    assert ab.avg_revs == pytest.approx(6.0)


def test_asymmetric_coupling_divides_by_the_less_active_file(db_session):
    """Locks in the exact formula: coupling_degree = shared_revs / min(revs(A), revs(B)).
    B is rarely touched (5 commits total) and every single one of those also
    touches the much busier A (10 commits total) -- that's the strongest kind
    of hidden-dependency signal, and dividing by the busier file (A) would
    crush the ratio down to 0.5 and hide it.
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/coupling-asymmetric")
    now = datetime.now(UTC)
    for i in range(5):
        _add_commit(db_session, repo_id, f"ab{i}", ["a.py", "b.py"], now)
    for i in range(5):
        _add_commit(db_session, repo_id, f"a_only{i}", ["a.py"], now)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    CouplingEngine().run(repo_id, run_id, db_session)
    db_session.commit()

    path_ids = _intern_paths(db_session, repo_id, ["a.py", "b.py"])
    rows = db_session.scalars(select(Coupling).where(Coupling.repo_id == repo_id)).all()
    row = next(
        r for r in rows if {r.path_a_id, r.path_b_id} == {path_ids["a.py"], path_ids["b.py"]}
    )
    assert row.shared_revs == 5
    # revs(a)=10, revs(b)=5 -> 5 / min(10, 5) = 1.0, not 5/10 = 0.5
    assert row.coupling_degree == pytest.approx(1.0)
    assert row.avg_revs == pytest.approx(7.5)


def test_asymmetric_coupling_at_larger_scale_still_divides_by_less_active_file(db_session):
    """Same locked-formula regression as above, at the scale explicitly
    called out for Phase 1: B has 6 commits total and all 6 also touch A,
    while A has 60 commits total. coupling_degree must still be
    6 / min(60, 6) = 1.0, not 6/60 = 0.1."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/coupling-asymmetric-large")
    now = datetime.now(UTC)
    for i in range(6):
        _add_commit(db_session, repo_id, f"ab{i}", ["a.py", "b.py"], now)
    for i in range(54):
        _add_commit(db_session, repo_id, f"a_only{i}", ["a.py"], now)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    CouplingEngine().run(repo_id, run_id, db_session)
    db_session.commit()

    path_ids = _intern_paths(db_session, repo_id, ["a.py", "b.py"])
    rows = db_session.scalars(select(Coupling).where(Coupling.repo_id == repo_id)).all()
    row = next(
        r for r in rows if {r.path_a_id, r.path_b_id} == {path_ids["a.py"], path_ids["b.py"]}
    )
    assert row.shared_revs == 6
    assert row.coupling_degree == pytest.approx(1.0)
    assert row.avg_revs == pytest.approx((60 + 6) / 2)


def test_mega_commit_is_dropped_as_noise(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/coupling-megacommit")
    now = datetime.now(UTC)
    for i in range(6):
        _add_commit(db_session, repo_id, f"xy{i}", ["x.py", "y.py"], now)
    # A 40-file changeset (merges/reformats) should be pure noise: dropped
    # entirely, not even counted toward x/y's shared_revs.
    mega_files = ["x.py", "y.py"] + [f"noise{i}.py" for i in range(38)]
    _add_commit(db_session, repo_id, "mega", mega_files, now)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = CouplingEngine().run(repo_id, run_id, db_session)
    db_session.commit()

    assert metadata["commits_analyzed"] == 6  # the 40-file commit was dropped

    rows = db_session.scalars(select(Coupling).where(Coupling.repo_id == repo_id)).all()
    path_by_id = _path_by_id(db_session, repo_id)
    xy = next(
        r for r in rows if {path_by_id[r.path_a_id], path_by_id[r.path_b_id]} == {"x.py", "y.py"}
    )
    assert xy.shared_revs == 6

    assert not any("noise0.py" in (path_by_id[r.path_a_id], path_by_id[r.path_b_id]) for r in rows)


def test_small_repo_fallback_marks_low_confidence_instead_of_empty(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/coupling-smallrepo")
    now = datetime.now(UTC)
    # Only 3 analyzed commits total -- fewer than MIN_SHARED_REVS (5), so
    # no pair could ever reach the normal floor. The fallback should
    # still produce a result rather than silently returning empty.
    assert MIN_SHARED_REVS > 3
    for i in range(3):
        _add_commit(db_session, repo_id, f"ab{i}", ["a.py", "b.py"], now)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = CouplingEngine().run(repo_id, run_id, db_session)
    db_session.commit()

    assert metadata["low_confidence"] is True
    assert metadata["commits_analyzed"] == 3

    rows = db_session.scalars(select(Coupling).where(Coupling.repo_id == repo_id)).all()
    assert len(rows) == 1
    ab = rows[0]
    assert ab.shared_revs == 3
    assert ab.shared_revs >= FALLBACK_MIN_SHARED_REVS

    assert confidence_hint(ab.shared_revs, low_confidence_repo=True) == "low"
    assert is_low_confidence(repo_id, db_session) is True


def test_fallback_triggers_when_no_pair_meets_the_floor_even_with_enough_commits(db_session):
    """Regression test for a real bug: a repo can have >= MIN_SHARED_REVS
    commits in total while no single PAIR ever reaches that floor (e.g. many
    scattered single-file commits, plus one pair that only co-changed
    twice). The old trigger for the small-repo fallback was "total analyzed
    commits < MIN_SHARED_REVS", which stayed False here and silently
    returned an empty pairs list with low_confidence=False on real repos
    with 13-16 commits. The fallback must instead trigger off whether the
    normal floor actually produced zero results.
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/coupling-scattered")
    now = datetime.now(UTC)
    # a.py and b.py co-change twice -- below MIN_SHARED_REVS (5).
    for i in range(2):
        _add_commit(db_session, repo_id, f"ab{i}", ["a.py", "b.py"], now)
    # 13 more commits, each touching one unique file alone -- no pair
    # among these ever co-occurs at all.
    for i in range(13):
        _add_commit(db_session, repo_id, f"solo{i}", [f"solo{i}.py"], now)
    db_session.commit()

    # Total analyzed commits is well above MIN_SHARED_REVS -- the old,
    # wrong trigger would never have engaged the fallback here.
    assert MIN_SHARED_REVS <= 2 + 13

    run_id = _make_run(db_session, repo_id)
    metadata = CouplingEngine().run(repo_id, run_id, db_session)
    db_session.commit()

    assert metadata["commits_analyzed"] == 15
    assert metadata["low_confidence"] is True
    assert metadata["pairs_found"] == 1

    rows = db_session.scalars(select(Coupling).where(Coupling.repo_id == repo_id)).all()
    assert len(rows) == 1
    assert rows[0].shared_revs == 2
    assert is_low_confidence(repo_id, db_session) is True
