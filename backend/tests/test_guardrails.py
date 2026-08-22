import ipaddress
import json
import urllib.error

import pytest

from app.ingestion.guardrails import check_github_repo_size, is_unsafe_ip, validate_repo_url


def test_accepts_valid_github_https_url():
    validate_repo_url("https://github.com/octocat/Hello-World")


def test_accepts_valid_gitlab_https_url():
    validate_repo_url("https://gitlab.com/gitlab-org/gitlab")


def test_rejects_non_https_scheme():
    with pytest.raises(ValueError):
        validate_repo_url("http://github.com/octocat/Hello-World")


def test_rejects_non_allowlisted_host():
    with pytest.raises(ValueError):
        validate_repo_url("https://evil.example.com/octocat/Hello-World")


def test_rejects_lookalike_subdomain_host():
    with pytest.raises(ValueError):
        validate_repo_url("https://github.com.evil.example.com/octocat/Hello-World")


def test_rejects_empty_url():
    with pytest.raises(ValueError):
        validate_repo_url("")


@pytest.mark.parametrize(
    "raw_ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "192.168.1.1",  # private
        "169.254.1.1",  # link-local
        "0.0.0.0",  # reserved
        "224.0.0.1",  # multicast
        "::1",  # loopback v6
        "fc00::1",  # unique local (private) v6
    ],
)
def test_is_unsafe_ip_flags_private_and_reserved_ranges(raw_ip):
    assert is_unsafe_ip(ipaddress.ip_address(raw_ip)) is True


@pytest.mark.parametrize("raw_ip", ["8.8.8.8", "1.1.1.1", "140.82.112.3"])
def test_is_unsafe_ip_allows_public_ips(raw_ip):
    assert is_unsafe_ip(ipaddress.ip_address(raw_ip)) is False


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_check_github_repo_size_allows_repo_under_the_cap(monkeypatch):
    import app.ingestion.guardrails as guardrails_module

    monkeypatch.setattr(
        guardrails_module.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"size": 100 * 1024}),  # 100 MB in KB
    )
    check_github_repo_size("octocat", "Hello-World", max_mb=300)


def test_check_github_repo_size_rejects_repo_over_the_cap(monkeypatch):
    import app.ingestion.guardrails as guardrails_module

    monkeypatch.setattr(
        guardrails_module.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"size": 500 * 1024}),  # 500 MB in KB
    )
    with pytest.raises(ValueError, match="too large"):
        check_github_repo_size("octocat", "Hello-World", max_mb=300)


def test_check_github_repo_size_does_not_block_on_api_failure(monkeypatch):
    """A GitHub API hiccup (rate limit, network error, timeout) must not
    block submission of an otherwise-valid repo."""
    import app.ingestion.guardrails as guardrails_module

    def raise_url_error(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(guardrails_module.urllib.request, "urlopen", raise_url_error)
    check_github_repo_size("octocat", "Hello-World", max_mb=300)  # does not raise


def test_check_github_repo_size_raises_on_404(monkeypatch):
    import app.ingestion.guardrails as guardrails_module

    def raise_not_found(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(guardrails_module.urllib.request, "urlopen", raise_not_found)
    with pytest.raises(ValueError, match="not found"):
        check_github_repo_size("octocat", "does-not-exist", max_mb=300)
