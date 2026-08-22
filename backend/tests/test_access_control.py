"""plan/RULES.md sec 9: ``require_repo_access`` guards every repo-scoped
endpoint, and this file is the test that catches the one you forget --
enumerating every route whose path contains ``/repos/{`` and asserting each
one declares ``require_repo_access`` as a dependency, plus direct tests of
``require_repo_access``'s own access rules.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.auth.deps import require_repo_access
from app.db.models import AnalysisRun, AnalysisRunStatus, Repo, RepoStatus, ShareLink, User
from app.main import app


def _declares_require_repo_access(route: APIRoute) -> bool:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    return any(dep.call is require_repo_access for dep in dependant.dependencies)


def test_every_repos_scoped_route_declares_require_repo_access():
    repo_scoped_routes = [
        route for route in app.routes if isinstance(route, APIRoute) and "/repos/{" in route.path
    ]
    assert repo_scoped_routes, "no /repos/{ routes found -- route discovery itself is broken"

    missing = [r.path for r in repo_scoped_routes if not _declares_require_repo_access(r)]
    assert not missing, f"routes missing require_repo_access: {missing}"


# ---------------------------------------------------------------------------
# require_repo_access's own access rules, exercised directly.
# ---------------------------------------------------------------------------


def _make_user(db_session, github_id: int) -> User:
    user = User(github_id=github_id, github_login=f"user-{github_id}")
    db_session.add(user)
    db_session.flush()
    return user


def _make_run(db_session, repo_id) -> AnalysisRun:
    run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.ready, head_sha="deadbeef")
    db_session.add(run)
    db_session.flush()
    return run


def test_public_repo_is_readable_by_anyone(db_session):
    repo = Repo(
        url="https://github.com/o/pub",
        owner="o",
        name="pub",
        status=RepoStatus.ready,
        is_private=False,
    )
    db_session.add(repo)
    db_session.flush()

    result = require_repo_access(repo_id=repo.id, db=db_session, user=None)
    assert result.id == repo.id


def test_private_repo_owner_is_allowed(db_session):
    owner = _make_user(db_session, 1)
    repo = Repo(
        url="https://github.com/o/priv1",
        owner="o",
        name="priv1",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()

    result = require_repo_access(repo_id=repo.id, db=db_session, user=owner)
    assert result.id == repo.id


def test_private_repo_other_authenticated_user_gets_403(db_session):
    owner = _make_user(db_session, 2)
    other = _make_user(db_session, 3)
    repo = Repo(
        url="https://github.com/o/priv2",
        owner="o",
        name="priv2",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        require_repo_access(repo_id=repo.id, db=db_session, user=other)
    assert exc_info.value.status_code == 403


def test_private_repo_anonymous_gets_403(db_session):
    owner = _make_user(db_session, 4)
    repo = Repo(
        url="https://github.com/o/priv3",
        owner="o",
        name="priv3",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        require_repo_access(repo_id=repo.id, db=db_session, user=None)
    assert exc_info.value.status_code == 403


def test_valid_unrevoked_share_link_grants_anonymous_access_to_its_run(db_session):
    owner = _make_user(db_session, 5)
    repo = Repo(
        url="https://github.com/o/priv4",
        owner="o",
        name="priv4",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()
    run = _make_run(db_session, repo.id)
    link = ShareLink(run_id=run.id, slug="share-slug-valid", created_by=owner.id)
    db_session.add(link)
    db_session.flush()

    result = require_repo_access(
        repo_id=repo.id, run_id=run.id, share=link.slug, db=db_session, user=None
    )
    assert result.id == repo.id


def test_revoked_share_link_gets_403(db_session):
    owner = _make_user(db_session, 6)
    repo = Repo(
        url="https://github.com/o/priv5",
        owner="o",
        name="priv5",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()
    run = _make_run(db_session, repo.id)
    link = ShareLink(
        run_id=run.id,
        slug="share-slug-revoked",
        created_by=owner.id,
        revoked_at=datetime.now(UTC),
    )
    db_session.add(link)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        require_repo_access(
            repo_id=repo.id, run_id=run.id, share=link.slug, db=db_session, user=None
        )
    assert exc_info.value.status_code == 403


def test_share_link_for_one_run_does_not_grant_access_to_a_different_run(db_session):
    owner = _make_user(db_session, 7)
    repo = Repo(
        url="https://github.com/o/priv6",
        owner="o",
        name="priv6",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()
    run_a = _make_run(db_session, repo.id)
    run_b = _make_run(db_session, repo.id)
    link = ShareLink(run_id=run_a.id, slug="share-slug-run-a", created_by=owner.id)
    db_session.add(link)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        require_repo_access(
            repo_id=repo.id, run_id=run_b.id, share=link.slug, db=db_session, user=None
        )
    assert exc_info.value.status_code == 403


def test_unknown_share_slug_gets_403_not_500(db_session):
    owner = _make_user(db_session, 8)
    repo = Repo(
        url="https://github.com/o/priv7",
        owner="o",
        name="priv7",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()
    run = _make_run(db_session, repo.id)

    with pytest.raises(HTTPException) as exc_info:
        require_repo_access(
            repo_id=repo.id, run_id=run.id, share="no-such-slug", db=db_session, user=None
        )
    assert exc_info.value.status_code == 403
