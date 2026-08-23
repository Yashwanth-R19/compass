import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    Coupling,
    ModuleCoupling,
    Repo,
    RepoPath,
    RepoStatus,
)
from app.engines.context import RunContext
from app.engines.coupling import CouplingEngine
from app.engines.module_coupling import MIN_SHARED_REVS_MODULE, ModuleCouplingEngine


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


def test_module_coupling_matches_locked_formula_and_differs_from_summed_file_pairs(db_session):
    """Session 04 Part G's core correctness test. Module A ("moda", 2 files)
    has 20 revs; module B ("modb", 2 files) has 6 revs, and ALL 6 of B's
    revs also touch module A. The LOCKED formula computed directly from
    module-level changesets must give coupling_degree == 1.0
    (6 / min(20, 6)). Then: compute what NAIVELY SUMMING the real,
    engine-computed FILE-PAIR coupling_degree values for the cross-module
    pairs would have given, and assert it differs -- the wrong
    implementation this test exists to keep out of the codebase.
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/module-coupling-correctness")
    now = datetime.now(UTC)

    # 3 commits touch moda/a1.py + modb/b1.py together.
    for i in range(3):
        _add_commit(db_session, repo_id, f"ab1-{i}", ["moda/a1.py", "modb/b1.py"], now)
    # 3 commits touch moda/a2.py + modb/b2.py together.
    for i in range(3):
        _add_commit(db_session, repo_id, f"ab2-{i}", ["moda/a2.py", "modb/b2.py"], now)
    # 7 + 7 more commits touch only ONE module-A file each -- module A's
    # revs reach 20 total (3+3+7+7); module B's stay at 6 (only the shared
    # commits touch any B file).
    for i in range(7):
        _add_commit(db_session, repo_id, f"a1-only-{i}", ["moda/a1.py"], now)
    for i in range(7):
        _add_commit(db_session, repo_id, f"a2-only-{i}", ["moda/a2.py"], now)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)

    CouplingEngine().run(ctx, db_session)
    db_session.commit()
    ModuleCouplingEngine().run(ctx, db_session)
    db_session.commit()

    module_row = db_session.scalar(
        select(ModuleCoupling).where(
            ModuleCoupling.analysis_run_id == run_id,
            ModuleCoupling.granularity == "directory",
            ModuleCoupling.module_a == "moda",
            ModuleCoupling.module_b == "modb",
        )
    )
    assert module_row is not None
    assert module_row.shared_revs == 6
    assert module_row.coupling_degree == pytest.approx(1.0)

    # Now the explicit wrong-implementation comparison: sum the REAL,
    # engine-computed file-pair coupling_degree values for the two
    # cross-module file pairs that actually co-occur.
    path_ids = _intern_paths(
        db_session, repo_id, ["moda/a1.py", "modb/b1.py", "moda/a2.py", "modb/b2.py"]
    )
    file_pair_rows = db_session.scalars(
        select(Coupling).where(Coupling.repo_id == repo_id, Coupling.analysis_run_id == run_id)
    ).all()

    def _degree_for(path_a: str, path_b: str) -> float:
        a_id, b_id = path_ids[path_a], path_ids[path_b]
        row = next(r for r in file_pair_rows if {r.path_a_id, r.path_b_id} == {a_id, b_id})
        return row.coupling_degree

    naive_sum = _degree_for("moda/a1.py", "modb/b1.py") + _degree_for("moda/a2.py", "modb/b2.py")

    assert naive_sum == pytest.approx(2.0)
    assert naive_sum != pytest.approx(module_row.coupling_degree)


def test_module_changeset_deduplicates_multiple_files_in_the_same_module(db_session):
    """Session 04 Part G: a commit touching 5 files in module A and 1 file
    in module B must count as ONE shared revision for the (A, B) pair, not
    five -- the whole point of collapsing a commit's changeset to the SET
    of distinct modules it touched before counting."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/module-coupling-dedup")
    now = datetime.now(UTC)

    moda_files = [f"moda/f{i}.py" for i in range(5)]
    for i in range(MIN_SHARED_REVS_MODULE):
        _add_commit(db_session, repo_id, f"multi-{i}", [*moda_files, "modb/b.py"], now)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    ModuleCouplingEngine().run(ctx, db_session)
    db_session.commit()

    row = db_session.scalar(
        select(ModuleCoupling).where(
            ModuleCoupling.analysis_run_id == run_id,
            ModuleCoupling.granularity == "directory",
            ModuleCoupling.module_a == "moda",
            ModuleCoupling.module_b == "modb",
        )
    )
    assert row is not None
    assert row.shared_revs == MIN_SHARED_REVS_MODULE  # not 5x that
    # revs(moda) == revs(modb) == MIN_SHARED_REVS_MODULE too (every commit
    # touches both modules) -> coupling_degree == 1.0.
    assert row.coupling_degree == pytest.approx(1.0)
