import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    Dependency,
    File,
    FileMetrics,
    Finding,
    Repo,
    RepoPath,
    RepoStatus,
)
from app.engines.context import RunContext
from app.engines.risk import RiskEngine
from app.engines.test_gaps import (
    MIN_COMMITS_FOR_STALE_CLASSIFICATION,
    TestGapEngine,
    compute_test_gaps,
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


def _add_file(
    db_session,
    repo_id: uuid.UUID,
    path: str,
    *,
    language: str = "python",
    is_test: bool = False,
    commit_count: int = 0,
) -> int:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path=path,
            language=language,
            current_loc=10,
            complexity=1.0,
            churn_total=1,
            commit_count=commit_count,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
            is_test=is_test,
        )
    )
    db_session.flush()
    return path_id


def _add_commit(db_session, repo_id: uuid.UUID, sha: str, file_paths: list[str]) -> None:
    path_ids = _intern_paths(db_session, repo_id, file_paths)
    db_session.execute(
        insert(Commit),
        [
            {
                "repo_id": repo_id,
                "sha": sha,
                "author_name": "tester",
                "author_email": "tester@example.com",
                "committed_at": datetime.now(UTC),
                "message": "synthetic change",
                "is_fix": False,
                "is_revert": False,
                "files_changed": len(file_paths),
                "insertions": 1,
                "deletions": 0,
                "changed_path_ids": [path_ids[p] for p in file_paths],
                "added_lines": [1 for _ in file_paths],
                "deleted_lines": [0 for _ in file_paths],
            }
        ],
    )


def _add_edge(db_session, repo_id: uuid.UUID, from_path: str, to_path: str) -> None:
    path_ids = _intern_paths(db_session, repo_id, [from_path, to_path])
    db_session.execute(
        insert(Dependency),
        [
            {
                "repo_id": repo_id,
                "from_path_id": path_ids[from_path],
                "to_path_id": path_ids[to_path],
                "dep_type": "import",
                "import_kind": "static",
            }
        ],
    )


def test_python_naming_convention_resolves(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-python")
    run_id = _make_run(db_session, repo_id)
    source_id = _add_file(db_session, repo_id, "pkg/foo.py", language="python")
    test_id = _add_file(db_session, repo_id, "pkg/test_foo.py", language="python", is_test=True)
    db_session.commit()

    result, _, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_id]["mapped_test_path_ids"] == [test_id]


def test_js_naming_convention_resolves(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-js")
    run_id = _make_run(db_session, repo_id)
    source_id = _add_file(db_session, repo_id, "src/Foo.ts", language="typescript")
    test_id = _add_file(db_session, repo_id, "src/Foo.test.ts", language="typescript", is_test=True)
    db_session.commit()

    result, _, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_id]["mapped_test_path_ids"] == [test_id]


def test_java_same_directory_naming_convention_resolves(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-java-samedir")
    run_id = _make_run(db_session, repo_id)
    source_id = _add_file(db_session, repo_id, "lib/Foo.java", language="java")
    test_id = _add_file(db_session, repo_id, "lib/FooTest.java", language="java", is_test=True)
    db_session.commit()

    result, _, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_id]["mapped_test_path_ids"] == [test_id]


def test_java_src_test_maps_to_src_main(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-java-srctest")
    run_id = _make_run(db_session, repo_id)
    source_id = _add_file(db_session, repo_id, "src/main/java/a/b/Foo.java", language="java")
    test_id = _add_file(
        db_session, repo_id, "src/test/java/a/b/FooTest.java", language="java", is_test=True
    )
    db_session.commit()

    result, _, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_id]["mapped_test_path_ids"] == [test_id]


def test_naming_convention_pointing_at_nonexistent_file_produces_no_mapping(db_session):
    """Session 07 Part C.2.a: "resolve against real paths only" -- a
    convention-shaped test file with no matching source anywhere produces
    NO mapping, never a guess."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-no-match")
    run_id = _make_run(db_session, repo_id)
    other_source_id = _add_file(db_session, repo_id, "unrelated.py", language="python")
    _add_file(db_session, repo_id, "test_ghost.py", language="python", is_test=True)
    db_session.commit()

    result, _, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert result[other_source_id]["classification"] == "no_test"
    assert result[other_source_id]["mapped_test_path_ids"] == []


def test_ambiguous_repo_wide_fallback_refuses_to_pick_one(db_session):
    """Known Hazard #5: the mirrored-directory path doesn't exist, so
    resolution falls back to a repo-wide unique-stem search -- but with TWO
    same-stem candidates in different directories, it must refuse rather
    than guess."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-ambiguous")
    run_id = _make_run(db_session, repo_id)
    source_a = _add_file(db_session, repo_id, "pkg1/foo.py", language="python")
    source_b = _add_file(db_session, repo_id, "pkg2/foo.py", language="python")
    _add_file(db_session, repo_id, "elsewhere/test_foo.py", language="python", is_test=True)
    db_session.commit()

    result, _, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_a]["mapped_test_path_ids"] == []
    assert result[source_b]["mapped_test_path_ids"] == []


def test_structural_mapping_via_dependency_edge(db_session):
    """Part C.2.b: a test file importing a non-test file counts as a
    mapping even when the naming convention itself doesn't apply."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-structural")
    run_id = _make_run(db_session, repo_id)
    source_id = _add_file(db_session, repo_id, "core.py", language="python")
    test_id = _add_file(db_session, repo_id, "tests/check_it.py", language="python", is_test=True)
    _add_edge(db_session, repo_id, "tests/check_it.py", "core.py")
    db_session.commit()

    result, _, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_id]["mapped_test_path_ids"] == [test_id]


def test_cochange_ratio_exactly_0_2_classifies_stale_test(db_session):
    """Required fixture: source changes 10 times, its mapped test changes in
    2 of those -> ratio == 0.2 -> "stale_test" (session 07's own spec/
    example conflict, resolved toward this fixture -- see
    STALE_TEST_RATIO_THRESHOLD's docstring)."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-cochange")
    run_id = _make_run(db_session, repo_id)
    source_id = _add_file(db_session, repo_id, "svc.py", language="python", commit_count=10)
    _add_file(db_session, repo_id, "test_svc.py", language="python", is_test=True)

    for i in range(10):
        if i < 2:
            _add_commit(db_session, repo_id, f"c{i}", ["svc.py", "test_svc.py"])
        else:
            _add_commit(db_session, repo_id, f"c{i}", ["svc.py"])
    db_session.commit()

    result, _, mean_ratio = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_id]["test_cochange_ratio"] == 0.2
    assert result[source_id]["classification"] == "stale_test"
    assert mean_ratio == 0.2


def test_low_commit_count_never_classifies_stale_even_with_zero_ratio(db_session):
    """Known Hazard #6: a file below MIN_COMMITS_FOR_STALE_CLASSIFICATION
    commits gets benefit of the doubt -- "tracked", never "stale_test",
    and is excluded from the repo-level mean."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-low-commits")
    run_id = _make_run(db_session, repo_id)
    assert MIN_COMMITS_FOR_STALE_CLASSIFICATION > 2
    source_id = _add_file(db_session, repo_id, "tiny.py", language="python", commit_count=2)
    _add_file(db_session, repo_id, "test_tiny.py", language="python", is_test=True)

    _add_commit(db_session, repo_id, "t1", ["tiny.py"])
    _add_commit(db_session, repo_id, "t2", ["tiny.py"])
    db_session.commit()

    result, _, mean_ratio = compute_test_gaps(repo_id, run_id, db_session)

    assert result[source_id]["classification"] == "tracked"
    assert mean_ratio == 0.0


def test_test_file_ratio_is_facts_derived(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-ratio")
    run_id = _make_run(db_session, repo_id)
    _add_file(db_session, repo_id, "a.py", language="python")
    _add_file(db_session, repo_id, "b.py", language="python")
    _add_file(db_session, repo_id, "test_a.py", language="python", is_test=True)
    db_session.commit()

    _, test_file_ratio, _ = compute_test_gaps(repo_id, run_id, db_session)

    assert test_file_ratio == 0.5  # 1 test file / 2 source files


def test_engine_updates_file_metrics_and_flags_top_risk_no_test_file(db_session):
    """Integration: TestGapEngine runs after RiskEngine in the "risk"
    stage, UPDATEs the file_metrics rows RiskEngine already inserted, and
    the flagship finding fires for a top-risk-quartile file with no
    mapped test."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/testgap-integration")
    run_id = _make_run(db_session, repo_id)

    hot_id = _add_file(db_session, repo_id, "hot.py", language="python", commit_count=10)
    _add_file(db_session, repo_id, "cold.py", language="python", commit_count=1)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    RiskEngine().run(ctx, db_session)
    db_session.commit()
    TestGapEngine().run(ctx, db_session)
    db_session.commit()

    metrics = {
        m.path_id: m
        for m in db_session.scalars(
            select(FileMetrics).where(FileMetrics.analysis_run_id == run_id)
        ).all()
    }
    assert metrics[hot_id].test_classification == "no_test"

    findings = db_session.scalars(
        select(Finding).where(Finding.analysis_run_id == run_id, Finding.category == "test_gap")
    ).all()
    assert any(f.path_id == hot_id for f in findings)
