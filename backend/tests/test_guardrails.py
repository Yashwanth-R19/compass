import ipaddress

import pytest

from app.ingestion.guardrails import is_unsafe_ip, validate_repo_url


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
