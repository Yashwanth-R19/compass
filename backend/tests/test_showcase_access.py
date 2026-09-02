"""Session 16, Part A: a showcase repo is publicly readable regardless of
authentication or its own ``is_private`` flag; a non-showcase private repo
is unaffected (still 403s an anonymous request), proving the exception is
scoped correctly rather than accidentally loosening access generally."""

from app.db.models import Repo, RepoStatus


def _make_repo(db_session, url: str, *, is_private: bool, is_showcase: bool) -> Repo:
    repo = Repo(
        url=url,
        owner="fixture",
        name="repo",
        status=RepoStatus.ready,
        is_private=is_private,
        is_showcase=is_showcase,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)
    return repo


def test_showcase_private_repo_is_readable_anonymously(client, db_session):
    repo = _make_repo(
        db_session, "https://github.com/fixture/showcase-private", is_private=True, is_showcase=True
    )
    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert resp.json()["is_showcase"] is True


def test_showcase_repo_response_carries_a_long_lived_cache_control_header(client, db_session):
    repo = _make_repo(
        db_session, "https://github.com/fixture/showcase-cache", is_private=False, is_showcase=True
    )
    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=3600, stale-while-revalidate=86400"


def test_ordinary_repo_response_carries_no_cache_control_header(client, db_session):
    repo = _make_repo(
        db_session, "https://github.com/fixture/ordinary-cache", is_private=False, is_showcase=False
    )
    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert "cache-control" not in resp.headers


def test_ordinary_private_repo_still_403s_anonymously(client, db_session):
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/private-not-showcase",
        is_private=True,
        is_showcase=False,
    )
    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 403


def test_list_showcase_repos_is_public_and_ordered_by_rank(client, db_session):
    r1 = _make_repo(
        db_session, "https://github.com/fixture/rank-2", is_private=False, is_showcase=True
    )
    r1.showcase_rank = 2
    r2 = _make_repo(
        db_session, "https://github.com/fixture/rank-1", is_private=False, is_showcase=True
    )
    r2.showcase_rank = 1
    db_session.commit()

    resp = client.get("/repos/showcase")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["repos"]]
    assert ids == [str(r2.id), str(r1.id)]


def test_visiting_a_repo_updates_last_viewed_at(client, db_session):
    repo = _make_repo(
        db_session, "https://github.com/fixture/touch-me", is_private=False, is_showcase=False
    )
    assert repo.last_viewed_at is None

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200

    db_session.refresh(repo)
    assert repo.last_viewed_at is not None
