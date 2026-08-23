"""Part F: symbols/repo_manifests persistence end-to-end through
run_ingestion_job, files.is_test classification, dependencies.import_kind,
and -- the "symptom of forgetting is duplicated symbols after a
re-analysis, which no test will catch unless you write one" hazard --
wipe_facts actually removing symbols/repo_manifests on a Facts replace.
"""

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import Dependency, File, Job, JobStatus, Repo, RepoManifest, RepoPath, RepoStatus
from app.db.models import Symbol as SymbolRow
from app.ingestion.persist import classify_is_test
from app.jobs.runner import run_ingestion_job


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_multi_language_fixture_repo(root: Path) -> Path:
    repo_dir = root / "fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    (repo_dir / "app.py").write_text("import helper\n\n\ndef main():\n    return helper.value\n")
    (repo_dir / "helper.py").write_text("value = 1\n")
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_app.py").write_text("def test_main():\n    assert True\n")

    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "index.ts").write_text(
        'import { helperValue } from "./helper";\nexport const x = helperValue;\n'
    )
    (repo_dir / "src" / "helper.ts").write_text("export const helperValue = 1;\n")

    (repo_dir / "com" / "example").mkdir(parents=True)
    (repo_dir / "com" / "example" / "Main.java").write_text(
        "package com.example;\npublic class Main {\n"
        "    public static void main(String[] args) {}\n"
        "}\n"
    )

    (repo_dir / "package.json").write_text('{"name": "fixture", "main": "src/index.ts"}\n')

    _git(repo_dir, "add", ".")
    _git(repo_dir, "commit", "-m", "initial multi-language fixture")

    return repo_dir


@pytest.fixture
def multi_language_repo(tmp_path):
    return _init_multi_language_fixture_repo(tmp_path)


def _make_repo_and_job(db_session, url: str) -> tuple:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.flush()
    job = Job(repo_id=repo.id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job)
    db_session.commit()
    return repo.id, job.id


def _new_job(db_session, repo_id):
    job = Job(repo_id=repo_id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job)
    db_session.commit()
    return job.id


def test_symbols_manifests_and_import_kind_persisted(multi_language_repo, db_session):
    repo_id, job_id = _make_repo_and_job(db_session, str(multi_language_repo))
    run_ingestion_job(repo_id, job_id)
    db_session.expire_all()

    symbols = db_session.scalars(select(SymbolRow).where(SymbolRow.repo_id == repo_id)).all()
    symbol_names = {s.name for s in symbols}
    assert "main" in symbol_names  # both app.py's def main() and Main.java's main()
    assert "x" not in symbol_names  # `export const x = helperValue` -- not an arrow function

    java_main = next(s for s in symbols if s.name == "main" and s.kind == "method")
    assert java_main.exported is True

    manifests = db_session.scalars(
        select(RepoManifest).where(RepoManifest.repo_id == repo_id)
    ).all()
    assert len(manifests) == 1
    assert manifests[0].kind == "package_json"
    assert manifests[0].data == {"name": "fixture", "main": "src/index.ts"}

    dependencies = db_session.scalars(select(Dependency).where(Dependency.repo_id == repo_id)).all()
    assert len(dependencies) >= 2  # app.py->helper.py, index.ts->helper.ts
    assert all(d.import_kind == "static" for d in dependencies)

    files = db_session.scalars(select(File).where(File.repo_id == repo_id)).all()
    files_by_path = {f.path: f for f in files}
    assert files_by_path["tests/test_app.py"].is_test is True
    assert files_by_path["app.py"].is_test is False
    assert files_by_path["src/index.ts"].is_test is False


def test_wipe_facts_removes_symbols_and_manifests_on_reanalysis(multi_language_repo, db_session):
    """The hazard this session's own instructions call out: forgetting to
    add symbols/repo_manifests to wipe_facts silently duplicates rows on
    every re-analysis. Assert the count stays the same, not doubled."""
    repo_id, job1_id = _make_repo_and_job(db_session, str(multi_language_repo))
    run_ingestion_job(repo_id, job1_id)
    db_session.expire_all()

    symbols_after_first = db_session.scalar(
        select(func.count()).select_from(SymbolRow).where(SymbolRow.repo_id == repo_id)
    )
    manifests_after_first = db_session.scalar(
        select(func.count()).select_from(RepoManifest).where(RepoManifest.repo_id == repo_id)
    )
    assert symbols_after_first > 0
    assert manifests_after_first > 0

    # A genuinely new commit -- head_sha must change, forcing the FACT
    # stages (including persist_facts's wipe_facts call) to run for real.
    (multi_language_repo / "helper.py").write_text("value = 2\n")
    _git(multi_language_repo, "add", "helper.py")
    _git(multi_language_repo, "commit", "-m", "bump helper value")

    job2_id = _new_job(db_session, repo_id)
    run_ingestion_job(repo_id, job2_id)
    db_session.expire_all()

    symbols_after_second = db_session.scalar(
        select(func.count()).select_from(SymbolRow).where(SymbolRow.repo_id == repo_id)
    )
    manifests_after_second = db_session.scalar(
        select(func.count()).select_from(RepoManifest).where(RepoManifest.repo_id == repo_id)
    )

    assert symbols_after_second == symbols_after_first
    assert manifests_after_second == manifests_after_first


def test_repo_paths_remain_stable_across_a_facts_replace_for_symbols(
    multi_language_repo, db_session
):
    """Symbols reference repo_paths.id (the permanent id), not files.id --
    a path present before and after a Facts replace must keep the same id
    so old Insight data referencing it (not exercised directly here, but
    the same invariant wipe_facts's docstring documents) stays valid."""
    repo_id, job1_id = _make_repo_and_job(db_session, str(multi_language_repo))
    run_ingestion_job(repo_id, job1_id)
    db_session.expire_all()

    app_py_id_before = db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == "app.py")
    )

    (multi_language_repo / "helper.py").write_text("value = 2\n")
    _git(multi_language_repo, "add", "helper.py")
    _git(multi_language_repo, "commit", "-m", "bump helper value")

    job2_id = _new_job(db_session, repo_id)
    run_ingestion_job(repo_id, job2_id)
    db_session.expire_all()

    app_py_id_after = db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == "app.py")
    )
    assert app_py_id_after == app_py_id_before


@pytest.mark.parametrize(
    ("path", "language", "expected"),
    [
        ("tests/test_app.py", "python", True),
        ("app/models.py", "python", False),
        ("conftest.py", "python", True),
        ("src/foo.test.ts", "typescript", True),
        ("src/foo.ts", "typescript", False),
        ("src/__tests__/foo.ts", "typescript", True),
        ("src/foo.spec.js", "javascript", True),
        ("src/components/Foo.tsx", "javascript", False),
        ("src/test/java/com/example/FooTest.java", "java", True),
        ("src/main/java/com/example/Foo.java", "java", False),
        ("src/main/java/com/example/FooIT.java", "java", True),
    ],
)
def test_classify_is_test(path: str, language: str, expected: bool):
    assert classify_is_test(path, language) is expected
