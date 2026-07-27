import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import Commit, File, Job, JobStatus, Repo, RepoPath, RepoStatus
from app.ingestion.cloner import clone_repo
from app.ingestion.miner import mine_repo
from app.jobs.runner import run_ingestion_job


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_fixture_repo(root: Path) -> Path:
    """A tiny local git repo with 3 commits touching known files, used to
    exercise clone -> mine -> persist without hitting a real remote.
    """
    repo_dir = root / "fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    (repo_dir / "a.py").write_text("def foo():\n    return 1\n")
    _git(repo_dir, "add", "a.py")
    _git(repo_dir, "commit", "-m", "add a.py")

    (repo_dir / "b.py").write_text("def bar():\n    return 2\n")
    (repo_dir / "a.py").write_text("def foo():\n    if True:\n        return 1\n    return 0\n")
    _git(repo_dir, "add", "a.py", "b.py")
    _git(repo_dir, "commit", "-m", "fix foo and add b.py")

    _git(repo_dir, "rm", "b.py")
    _git(repo_dir, "commit", "-m", "remove b.py")

    return repo_dir


@pytest.fixture
def fixture_repo(tmp_path):
    return _init_fixture_repo(tmp_path)


def _make_repo_and_job(db_session, url: str) -> tuple:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.flush()
    job = Job(repo_id=repo.id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job)
    db_session.commit()
    return repo.id, job.id


def test_mine_and_persist_fixture_repo(fixture_repo, db_session, monkeypatch):
    captured_clone_path = {}
    original_clone = clone_repo

    def spy_clone(url):
        path = original_clone(url)
        captured_clone_path["path"] = path
        return path

    monkeypatch.setattr("app.jobs.runner.clone_repo", spy_clone)

    repo_id, job_id = _make_repo_and_job(db_session, str(fixture_repo))

    run_ingestion_job(repo_id, job_id)

    # Clone is disposable: it must be gone once the job finishes.
    assert "path" in captured_clone_path
    assert not Path(captured_clone_path["path"]).exists()

    commits = db_session.scalars(select(Commit).where(Commit.repo_id == repo_id)).all()
    files = db_session.scalars(select(File).where(File.repo_id == repo_id)).all()

    assert len(commits) == 3

    files_by_path = {f.path: f for f in files}
    assert set(files_by_path) == {"a.py", "b.py"}
    assert files_by_path["b.py"].is_deleted is True
    assert files_by_path["a.py"].is_deleted is False
    assert files_by_path["a.py"].commit_count == 2

    # commit1 touches a.py; commit2 touches a.py+b.py; commit3 touches b.py --
    # changed_path_ids replaces the old commit_files join table (Phase 1).
    total_touches = sum(len(c.changed_path_ids) for c in commits)
    assert total_touches == 4

    for c in commits:
        assert len(c.changed_path_ids) == len(c.added_lines) == len(c.deleted_lines)

    path_ids = {row for c in commits for row in c.changed_path_ids}
    real_path_ids = set(
        db_session.scalars(select(RepoPath.id).where(RepoPath.repo_id == repo_id)).all()
    )
    assert path_ids <= real_path_ids

    job = db_session.get(Job, job_id)
    assert job.status == JobStatus.done
    assert job.progress == 100
    assert job.error is None

    repo = db_session.get(Repo, repo_id)
    assert repo.status == RepoStatus.ready
    assert repo.commit_count == 3


def _touch_count(db_session, repo_id) -> int:
    commits = db_session.scalars(select(Commit).where(Commit.repo_id == repo_id)).all()
    return sum(len(c.changed_path_ids) for c in commits)


def test_reingestion_is_idempotent_full_replace(fixture_repo, db_session):
    repo_id, job1_id = _make_repo_and_job(db_session, str(fixture_repo))

    run_ingestion_job(repo_id, job1_id)
    db_session.expire_all()
    commits_after_first = db_session.scalar(
        select(func.count()).select_from(Commit).where(Commit.repo_id == repo_id)
    )
    files_after_first = db_session.scalar(
        select(func.count()).select_from(File).where(File.repo_id == repo_id)
    )
    repo_paths_after_first = db_session.scalar(
        select(func.count()).select_from(RepoPath).where(RepoPath.repo_id == repo_id)
    )
    touches_after_first = _touch_count(db_session, repo_id)

    job2 = Job(repo_id=repo_id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job2)
    db_session.commit()

    run_ingestion_job(repo_id, job2.id)
    db_session.expire_all()
    commits_after_second = db_session.scalar(
        select(func.count()).select_from(Commit).where(Commit.repo_id == repo_id)
    )
    files_after_second = db_session.scalar(
        select(func.count()).select_from(File).where(File.repo_id == repo_id)
    )
    repo_paths_after_second = db_session.scalar(
        select(func.count()).select_from(RepoPath).where(RepoPath.repo_id == repo_id)
    )
    touches_after_second = _touch_count(db_session, repo_id)

    assert commits_after_first == 3
    assert commits_after_second == commits_after_first
    assert files_after_second == files_after_first
    assert repo_paths_after_second == repo_paths_after_first
    assert touches_after_second == touches_after_first


def test_mined_paths_are_posix_even_on_windows(tmp_path):
    """Regression test: the miner normalizes every path to forward slashes
    (app/ingestion/miner.py's ``_normalize_path``) even though git's own
    --numstat output is already posix -- defense in depth, since a backslash
    path would silently break `is_deleted` (comparing it against
    `_final_tree_paths`' posix set never matches) and the hidden-dependency
    overlay too, since app/languages/scanner.py always produces posix paths.
    The original fixture repo (top-level a.py/b.py only) never caught this
    because a bare filename has no separator to get mangled.
    """
    repo_dir = tmp_path / "nested-fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    (repo_dir / "pkg").mkdir()
    (repo_dir / "pkg" / "a.py").write_text("value = 1\n")
    _git(repo_dir, "add", "pkg/a.py")
    _git(repo_dir, "commit", "-m", "add pkg/a.py")

    (repo_dir / "pkg" / "b.py").write_text("value = 2\n")
    _git(repo_dir, "add", "pkg/b.py")
    _git(repo_dir, "commit", "-m", "add pkg/b.py")

    mined = mine_repo(str(repo_dir))

    paths = {f.path for f in mined.files}
    assert paths == {"pkg/a.py", "pkg/b.py"}
    assert not any("\\" in p for p in paths)

    files_by_path = {f.path: f for f in mined.files}
    assert files_by_path["pkg/a.py"].is_deleted is False
    assert files_by_path["pkg/b.py"].is_deleted is False

    for commit in mined.commits:
        assert not any("\\" in p for p in commit.file_paths)
