import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.db.models import Commit, CommitFile, File, Job, JobStatus, Repo, RepoStatus
from app.db.wipe import wipe_repo_data
from app.ingestion.cloner import clone_repo
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


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_repo_and_job(db_session, url: str) -> tuple:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.flush()
    job = Job(repo_id=repo.id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job)
    db_session.commit()
    return repo.id, job.id


def _cleanup_repo(db_session, repo_id) -> None:
    wipe_repo_data(repo_id, db_session)
    db_session.query(Job).filter(Job.repo_id == repo_id).delete()
    db_session.query(Repo).filter(Repo.id == repo_id).delete()
    db_session.commit()


def test_mine_and_persist_fixture_repo(fixture_repo, db_session, monkeypatch):
    captured_clone_path = {}
    original_clone = clone_repo

    def spy_clone(url):
        path = original_clone(url)
        captured_clone_path["path"] = path
        return path

    monkeypatch.setattr("app.jobs.runner.clone_repo", spy_clone)

    repo_id, job_id = _make_repo_and_job(db_session, str(fixture_repo))

    try:
        run_ingestion_job(repo_id, job_id)

        # Clone is disposable: it must be gone once the job finishes.
        assert "path" in captured_clone_path
        assert not Path(captured_clone_path["path"]).exists()

        commits = db_session.scalars(select(Commit).where(Commit.repo_id == repo_id)).all()
        files = db_session.scalars(select(File).where(File.repo_id == repo_id)).all()
        commit_files = db_session.scalars(
            select(CommitFile).where(CommitFile.commit_id.in_([c.id for c in commits]))
        ).all()

        assert len(commits) == 3

        files_by_path = {f.path: f for f in files}
        assert set(files_by_path) == {"a.py", "b.py"}
        assert files_by_path["b.py"].is_deleted is True
        assert files_by_path["a.py"].is_deleted is False
        assert files_by_path["a.py"].commit_count == 2

        # commit1 touches a.py; commit2 touches a.py+b.py; commit3 touches b.py
        assert len(commit_files) == 4

        job = db_session.get(Job, job_id)
        assert job.status == JobStatus.done
        assert job.progress == 100
        assert job.error is None

        repo = db_session.get(Repo, repo_id)
        assert repo.status == RepoStatus.ready
        assert repo.commit_count == 3
    finally:
        _cleanup_repo(db_session, repo_id)


def test_reingestion_is_idempotent_full_replace(fixture_repo, db_session):
    repo_id, job1_id = _make_repo_and_job(db_session, str(fixture_repo))

    try:
        run_ingestion_job(repo_id, job1_id)
        db_session.expire_all()
        commits_after_first = db_session.scalar(
            select(func.count()).select_from(Commit).where(Commit.repo_id == repo_id)
        )
        files_after_first = db_session.scalar(
            select(func.count()).select_from(File).where(File.repo_id == repo_id)
        )
        commit_files_after_first = db_session.scalar(
            select(func.count())
            .select_from(CommitFile)
            .join(Commit, Commit.id == CommitFile.commit_id)
            .where(Commit.repo_id == repo_id)
        )

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
        commit_files_after_second = db_session.scalar(
            select(func.count())
            .select_from(CommitFile)
            .join(Commit, Commit.id == CommitFile.commit_id)
            .where(Commit.repo_id == repo_id)
        )

        assert commits_after_first == 3
        assert commits_after_second == commits_after_first
        assert files_after_second == files_after_first
        assert commit_files_after_second == commit_files_after_first
    finally:
        _cleanup_repo(db_session, repo_id)
