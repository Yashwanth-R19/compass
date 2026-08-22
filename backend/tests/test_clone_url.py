import logging

import pytest

from app.auth.crypto import encrypt_token
from app.db.models import Repo, RepoStatus, User
from app.ingestion.clone_url import resolve_clone_url
from app.ingestion.cloner import clone_repo


def _make_owner(db_session, token: str) -> User:
    user = User(
        github_id=100,
        github_login="owner",
        access_token_encrypted=encrypt_token(token),
        token_scopes="read:user repo",
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_resolve_clone_url_returns_plain_url_for_public_repo(db_session):
    repo = Repo(
        url="https://github.com/o/pub",
        owner="o",
        name="pub",
        status=RepoStatus.ready,
        is_private=False,
    )
    db_session.add(repo)
    db_session.flush()

    assert resolve_clone_url(repo, db_session) == repo.url


def test_resolve_clone_url_embeds_token_for_private_repo(db_session):
    owner = _make_owner(db_session, "gho_supersecrettoken1234567890")
    repo = Repo(
        url="https://github.com/o/priv",
        owner="o",
        name="priv",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=owner.id,
    )
    db_session.add(repo)
    db_session.flush()

    url = resolve_clone_url(repo, db_session)
    assert url == "https://x-access-token:gho_supersecrettoken1234567890@github.com/o/priv"


def test_resolve_clone_url_raises_when_owner_has_no_stored_token(db_session):
    owner = User(github_id=101, github_login="no-token-owner")
    db_session.add(owner)
    db_session.flush()
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

    with pytest.raises(ValueError):
        resolve_clone_url(repo, db_session)


def test_resolve_clone_url_raises_when_private_repo_has_no_owner(db_session):
    repo = Repo(
        url="https://github.com/o/priv3",
        owner="o",
        name="priv3",
        status=RepoStatus.ready,
        is_private=True,
        owner_user_id=None,
    )
    db_session.add(repo)
    db_session.flush()

    with pytest.raises(ValueError):
        resolve_clone_url(repo, db_session)


def test_token_never_appears_in_log_output_during_a_failed_clone(caplog):
    """A failed clone against a credentialed URL must never leak the token
    through git's own error output (plan/RULES.md sec 10's "known hazard").
    Points at a fast-failing local address (connection refused) rather than
    a real remote, so this stays offline and fast."""
    token = "gho_supersecrettoken1234567890abcdefghij"
    bad_url = f"https://x-access-token:{token}@127.0.0.1:1/no-such-repo.git"

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as exc_info:
        clone_repo(bad_url)

    assert token not in str(exc_info.value)
    for record in caplog.records:
        assert token not in record.getMessage()
