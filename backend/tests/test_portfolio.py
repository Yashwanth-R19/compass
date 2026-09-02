"""session 14, Part B/F -- portfolio aggregation and its access control."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.analysis.portfolio import compute_portfolio
from app.api.portfolio import _already_up_to_date
from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    File,
    Repo,
    RepoPath,
    RepoStatus,
    User,
)
from app.ingestion.cloner import get_remote_head_sha


def _login(client, user: User) -> None:
    token = create_session_token(user.id)
    client.cookies.set(SESSION_COOKIE_NAME, token)


def _make_user(db_session, github_id: int) -> User:
    user = User(github_id=github_id, github_login=f"user-{github_id}")
    db_session.add(user)
    db_session.flush()
    return user


def _make_ready_repo(db_session, owner_user_id, name: str) -> Repo:
    repo = Repo(
        url=f"https://github.com/o/{name}",
        owner="o",
        name=name,
        status=RepoStatus.ready,
        owner_user_id=owner_user_id,
        head_sha="deadbeef",
    )
    db_session.add(repo)
    db_session.flush()

    run = AnalysisRun(
        repo_id=repo.id, status=AnalysisRunStatus.ready, head_sha="deadbeef", engine_version=2
    )
    db_session.add(run)
    db_session.flush()
    repo.current_run_id = run.id
    db_session.flush()
    return repo, run


def _add_commit(db_session, repo_id, author_name: str, author_email: str, when: datetime) -> None:
    db_session.add(
        Commit(
            repo_id=repo_id,
            sha=f"sha-{author_email}-{when.isoformat()}",
            author_name=author_name,
            author_email=author_email,
            committed_at=when,
            message="a commit",
            files_changed=1,
            insertions=1,
            deletions=0,
        )
    )


def _add_file(db_session, repo_id, path: str, loc: int = 10) -> None:
    repo_path = RepoPath(repo_id=repo_id, path=path)
    db_session.add(repo_path)
    db_session.flush()
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=repo_path.id,
            path=path,
            language="python",
            current_loc=loc,
            complexity=1.0,
            first_seen=datetime.now(UTC),
            last_seen=datetime.now(UTC),
        )
    )


def test_compute_portfolio_is_empty_for_user_with_no_ready_repos(db_session):
    user = _make_user(db_session, 5001)
    db_session.commit()

    data = compute_portfolio(db_session, user.id)
    assert data["repository_count"] == 0
    assert data["totals"]["contributors"] == 0


def test_portfolio_contributor_dedup_across_repositories(db_session):
    """The same human under a work email in one repo and a personal email
    in another must count ONCE in the pooled contributor total -- proving
    the dedup actually spans repositories, not just files within one."""
    user = _make_user(db_session, 5002)
    repo1, _run1 = _make_ready_repo(db_session, user.id, "repo-a")
    repo2, _run2 = _make_ready_repo(db_session, user.id, "repo-b")
    repo3, _run3 = _make_ready_repo(db_session, user.id, "repo-c")
    db_session.flush()

    now = datetime.now(UTC)
    # Jane appears under the SAME email in all three repos -- rule 1 (exact
    # email match) merges her into one identity regardless of repo.
    _add_commit(db_session, repo1.id, "Jane Doe", "jane@corp.com", now)
    _add_commit(db_session, repo2.id, "Jane Doe", "jane@corp.com", now)
    _add_commit(db_session, repo3.id, "Jane Doe", "jane@corp.com", now)
    # Bob only ever appears in repo1 -- a second, distinct contributor.
    _add_commit(db_session, repo1.id, "Bob Smith", "bob@corp.com", now)
    db_session.commit()

    data = compute_portfolio(db_session, user.id)
    assert data["repository_count"] == 3
    assert data["totals"]["contributors"] == 2
    assert data["totals"]["commits"] == 0  # commit_count column, not raw Commit rows, per repo


def test_portfolio_only_counts_the_caller_own_repositories(db_session, client):
    user_a = _make_user(db_session, 5003)
    user_b = _make_user(db_session, 5004)
    repo_a, _ = _make_ready_repo(db_session, user_a.id, "only-a")
    _add_file(db_session, repo_a.id, "a.py")
    repo_b, _ = _make_ready_repo(db_session, user_b.id, "only-b")
    _add_file(db_session, repo_b.id, "b.py")
    _add_file(db_session, repo_b.id, "c.py")
    db_session.commit()

    _login(client, user_a)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repository_count"] == 1
    assert body["totals"]["files"] == 1  # only repo_a's file, never repo_b's

    _login(client, user_b)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repository_count"] == 1
    assert body["totals"]["files"] == 2


def test_portfolio_requires_authentication(client):
    resp = client.get("/portfolio")
    assert resp.status_code == 401


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_already_up_to_date_skips_repo_at_current_head_sha(tmp_path, db_session):
    repo_dir = tmp_path / "portfolio-skip-fixture"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "t@example.com")
    _git(repo_dir, "config", "user.name", "T")
    (repo_dir / "a.py").write_text("x = 1\n")
    _git(repo_dir, "add", "a.py")
    _git(repo_dir, "commit", "-m", "init")

    url = str(repo_dir)
    real_head_sha = get_remote_head_sha(url)

    repo = Repo(
        url=url, owner="local", name="skip", status=RepoStatus.ready, head_sha=real_head_sha
    )
    db_session.add(repo)
    db_session.flush()
    run = AnalysisRun(repo_id=repo.id, status=AnalysisRunStatus.ready, head_sha=real_head_sha)
    db_session.add(run)
    db_session.flush()
    repo.current_run_id = run.id
    db_session.commit()

    assert _already_up_to_date(repo, db_session) is True

    # A new commit moves the remote head_sha -- no longer up to date.
    (repo_dir / "b.py").write_text("y = 2\n")
    _git(repo_dir, "add", "b.py")
    _git(repo_dir, "commit", "-m", "second commit")
    assert _already_up_to_date(repo, db_session) is False


def test_already_up_to_date_false_for_repo_never_analyzed(db_session):
    repo = Repo(
        url="https://github.com/o/never", owner="o", name="never", status=RepoStatus.pending
    )
    db_session.add(repo)
    db_session.commit()
    assert _already_up_to_date(repo, db_session) is False
