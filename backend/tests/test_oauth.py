import pytest

from app.api import auth as auth_module


@pytest.mark.parametrize(
    "next_value",
    ["https://evil.com", "//evil.com", "/\\evil.com", "https:/evil.com"],
)
def test_validate_next_path_rejects_open_redirect_targets(next_value):
    with pytest.raises(Exception) as exc_info:
        auth_module._validate_next_path(next_value)
    assert getattr(exc_info.value, "status_code", None) == 400


def test_validate_next_path_accepts_a_plain_relative_path():
    assert auth_module._validate_next_path("/repos/abc/overview") == "/repos/abc/overview"


def test_validate_next_path_defaults_to_root_when_absent():
    assert auth_module._validate_next_path(None) == "/"
    assert auth_module._validate_next_path("") == "/"


def test_login_sets_state_cookie_and_redirects_to_github(client):
    response = client.get("/auth/github/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://github.com/login/oauth/authorize")
    assert auth_module.OAUTH_STATE_COOKIE_NAME in response.cookies


def test_callback_rejects_state_mismatch(client):
    client.get("/auth/github/login", follow_redirects=False)

    response = client.get(
        "/auth/github/callback",
        params={"code": "irrelevant", "state": "this-does-not-match-the-cookie"},
    )
    assert response.status_code == 400


def test_callback_rejects_missing_state_cookie(client):
    response = client.get(
        "/auth/github/callback", params={"code": "irrelevant", "state": "whatever"}
    )
    assert response.status_code == 400
