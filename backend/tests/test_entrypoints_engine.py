import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Dependency,
    EntryPoint,
    File,
    Repo,
    RepoManifest,
    RepoPath,
    RepoStatus,
)
from app.db.models import Symbol as SymbolRow
from app.engines.context import RunContext
from app.engines.entrypoints import EntryPointEngine, compute_entry_points


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


def _add_file(db_session, repo_id: uuid.UUID, path: str, *, is_test: bool = False) -> int:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    now = datetime.now(UTC)
    db_session.add(
        File(
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
            is_test=is_test,
        )
    )
    db_session.flush()
    return path_id


def _add_manifest(db_session, repo_id: uuid.UUID, path: str, kind: str, data: dict) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(RepoManifest),
        [{"repo_id": repo_id, "path_id": path_id, "kind": kind, "data": data}],
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


def _add_symbol(
    db_session, repo_id: uuid.UUID, path: str, *, name: str, kind: str, exported: bool
) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(SymbolRow),
        [
            {
                "repo_id": repo_id,
                "path_id": path_id,
                "name": name,
                "kind": kind,
                "line": 1,
                "exported": exported,
            }
        ],
    )


def test_all_detection_rules_produce_the_expected_evidence_strings(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/entrypoints-all-rules")

    # 1. package.json scripts.dev -> a real file.
    _add_file(db_session, repo_id, "src/server.js")
    _add_manifest(
        db_session,
        repo_id,
        "package.json",
        "package_json",
        {"scripts": {"dev": "node src/server.js"}},
    )

    # 2. Dockerfile CMD -> a real file.
    _add_file(db_session, repo_id, "run_server.py")
    _add_manifest(
        db_session, repo_id, "Dockerfile", "dockerfile", {"CMD": ["python", "run_server.py"]}
    )

    # 3. Conventional filename: manage.py.
    _add_file(db_session, repo_id, "manage.py")

    # 4. Java main method.
    _add_file(db_session, repo_id, "com/example/Main.java")
    _add_symbol(
        db_session, repo_id, "com/example/Main.java", name="main", kind="method", exported=True
    )

    # 5. Graph-inferred: cli_tool.py imports 3 files, nothing imports it.
    _add_file(db_session, repo_id, "cli_tool.py")
    for i in range(3):
        target = f"dep{i}.py"
        _add_file(db_session, repo_id, target)
        _add_dependency(db_session, repo_id, "cli_tool.py", target)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    metadata = EntryPointEngine().run(ctx, db_session)
    db_session.commit()

    rows = db_session.scalars(
        select(EntryPoint).where(EntryPoint.analysis_run_id == run_id).order_by(EntryPoint.rank)
    ).all()
    path_map = {
        row.id: row.path
        for row in db_session.execute(
            select(RepoPath.id, RepoPath.path).where(RepoPath.repo_id == repo_id)
        ).all()
    }
    by_path = {path_map[r.path_id]: r for r in rows}

    assert metadata["entry_points"] == len(rows)

    server = by_path["src/server.js"]
    assert server.evidence == "package.json scripts.dev references this file"
    assert server.kind == "web_server"
    assert server.confidence == 0.95

    docker = by_path["run_server.py"]
    assert docker.evidence == "Dockerfile CMD"
    assert docker.kind == "web_server"
    assert docker.confidence == 0.95

    manage = by_path["manage.py"]
    assert manage.evidence == "conventional filename: manage.py"
    assert manage.kind == "cli"
    assert manage.confidence == 0.75

    java_main = by_path["com/example/Main.java"]
    assert java_main.evidence == "Java public static void main method"
    assert java_main.kind == "cli"
    assert java_main.confidence == 0.75

    cli_tool = by_path["cli_tool.py"]
    assert cli_tool.evidence == "no inbound imports, 3 outbound"
    assert cli_tool.kind == "graph_inferred"
    assert cli_tool.confidence == 0.5

    # Ranked confidence desc -- the manifest/java/conventional detections
    # (0.95/0.95/0.75/0.75) all outrank the graph-inferred one (0.5).
    ranks = [r.rank for r in rows]
    assert ranks == sorted(ranks)
    assert rows[-1].id == cli_tool.id


def test_manifest_script_pointing_at_a_nonexistent_file_produces_no_entry_point(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/entrypoints-missing-file")
    _add_manifest(
        db_session,
        repo_id,
        "package.json",
        "package_json",
        {"scripts": {"start": "node missing_file.js"}},
    )
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows = compute_entry_points(repo_id, run_id, db_session, ctx)

    assert rows == []


def test_repo_with_no_imports_does_not_crash_and_produces_no_graph_inferred_entries(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/entrypoints-no-imports")
    _add_file(db_session, repo_id, "lonely.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    metadata = EntryPointEngine().run(ctx, db_session)
    db_session.commit()

    assert metadata["entry_points"] == 0


def test_test_root_reports_the_directory_via_one_representative_file(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/entrypoints-test-root")
    _add_file(db_session, repo_id, "tests/test_a.py", is_test=True)
    _add_file(db_session, repo_id, "tests/test_b.py", is_test=True)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows = compute_entry_points(repo_id, run_id, db_session, ctx)

    test_root_rows = [r for r in rows if r["kind"] == "test_root"]
    assert len(test_root_rows) == 1  # one row for the directory, not one per file
    assert test_root_rows[0]["evidence"] == "test directory: tests/"
    assert test_root_rows[0]["confidence"] == 0.9
