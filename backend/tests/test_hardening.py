"""Session 16, Part C/D: abuse hardening and admin-endpoint access control."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.db.models import Repo, RepoStatus, User
from app.jobs.runner import SOFT_TIMEOUT_MINUTES, _check_soft_timeout, _SoftTimeoutExceeded


def _login(client, user: User) -> None:
    token = create_session_token(user.id)
    client.cookies.set(SESSION_COOKIE_NAME, token)


def _make_user(db_session, github_id: int) -> User:
    user = User(github_id=github_id, github_login=f"user-{github_id}")
    db_session.add(user)
    db_session.commit()
    return user


def test_soft_timeout_does_not_fire_before_the_limit():
    started = datetime.now(UTC) - timedelta(minutes=SOFT_TIMEOUT_MINUTES - 1)
    _check_soft_timeout(started)  # must not raise


def test_soft_timeout_fires_after_the_limit():
    started = datetime.now(UTC) - timedelta(minutes=SOFT_TIMEOUT_MINUTES + 1)
    try:
        _check_soft_timeout(started)
        raised = False
    except _SoftTimeoutExceeded:
        raised = True
    assert raised


def test_security_headers_present_on_every_response(client):
    resp = client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    assert "strict-transport-security" in resp.headers
    assert "x-request-id" in resp.headers


def test_oversized_request_body_is_rejected(client):
    huge = "x" * (2 * 1024 * 1024)
    resp = client.post(
        "/repos",
        content=huge,
        headers={"content-length": str(len(huge)), "content-type": "application/json"},
    )
    assert resp.status_code == 413


def test_user_repo_cap_blocks_once_reached(db_session, monkeypatch):
    """Calls ``check_user_repo_cap`` directly, the same way
    ``tests/test_rate_limits.py`` tests ``check_concurrency_cap`` -- avoids a
    real network call to GitHub, which the full ``POST /repos`` endpoint
    would otherwise make via ``check_github_repo_visibility``."""
    import app.api.limits as limits_module
    from app.api.limits import check_user_repo_cap

    monkeypatch.setattr(limits_module, "MAX_REPOS_PER_USER", 1)

    user = _make_user(db_session, github_id=555)
    db_session.add(
        Repo(
            url="https://github.com/fixture/already-owned",
            owner="fixture",
            name="already-owned",
            status=RepoStatus.ready,
            owner_user_id=user.id,
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        check_user_repo_cap(user, db_session)
    assert exc_info.value.status_code == 409


def test_user_repo_cap_allows_submission_under_the_limit(db_session):
    from app.api.limits import check_user_repo_cap

    user = _make_user(db_session, github_id=556)
    check_user_repo_cap(user, db_session)  # no owned repos at all -- must not raise


def test_delete_repo_requires_ownership(client, db_session):
    owner = _make_user(db_session, github_id=111)
    other = _make_user(db_session, github_id=222)
    repo = Repo(
        url="https://github.com/fixture/owned-repo",
        owner="fixture",
        name="owned-repo",
        status=RepoStatus.ready,
        owner_user_id=owner.id,
        is_private=False,
    )
    db_session.add(repo)
    db_session.commit()

    _login(client, other)
    resp = client.delete(f"/repos/{repo.id}")
    assert resp.status_code == 403

    _login(client, owner)
    resp = client.delete(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}
    assert db_session.get(Repo, repo.id) is None


def test_delete_repo_refuses_a_showcase_repo(client, db_session):
    owner = _make_user(db_session, github_id=333)
    repo = Repo(
        url="https://github.com/fixture/pinned",
        owner="fixture",
        name="pinned",
        status=RepoStatus.ready,
        owner_user_id=owner.id,
        is_showcase=True,
        showcase_rank=1,
    )
    db_session.add(repo)
    db_session.commit()

    _login(client, owner)
    resp = client.delete(f"/repos/{repo.id}")
    assert resp.status_code == 403
    assert db_session.get(Repo, repo.id) is not None


def test_internal_endpoints_require_admin_token(client, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module.settings, "COMPASS_ADMIN_TOKEN", "")
    resp = client.get("/internal/storage")
    assert resp.status_code == 503

    monkeypatch.setattr(config_module.settings, "COMPASS_ADMIN_TOKEN", "the-real-token")
    resp = client.get("/internal/storage")
    assert resp.status_code == 401

    resp = client.get("/internal/storage", headers={"x-admin-token": "the-real-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert "total_bytes" in body
    assert "tables" in body


def test_internal_stats_reports_counts(client, db_session, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module.settings, "COMPASS_ADMIN_TOKEN", "the-real-token")
    db_session.add(
        Repo(url="https://github.com/fixture/stats-repo", owner="fixture", name="stats-repo")
    )
    db_session.commit()

    resp = client.get("/internal/stats", headers={"x-admin-token": "the-real-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["repos"] >= 1
    assert "stage_stats" in body
    assert "rate_limit_rejections" in body
