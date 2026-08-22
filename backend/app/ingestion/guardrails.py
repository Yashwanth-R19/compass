import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {"github.com", "gitlab.com"}

_GITHUB_API_TIMEOUT_SECONDS = 10.0
"""On the POST /repos request path -- a hung GitHub API call must not hang
repo creation. See check_github_repo_size's docstring for what happens on
timeout/failure."""


class RepoAccessRequired(Exception):
    """Raised by ``check_github_repo_visibility`` when an anonymous lookup
    404s and no usable token was available to retry authenticated (session
    02, Part D). GitHub itself returns 404 for both "doesn't exist" and
    "exists but private and you can't see it" -- deliberately
    indistinguishable, to avoid leaking which private repos exist. This
    exception preserves that ambiguity rather than guessing: the caller
    (``POST /repos``) turns it into a 403 telling the user to connect
    private repositories, which is the right next step whether the repo
    turns out to be private or simply doesn't exist.
    """


def _fetch_github_repo(owner: str, name: str, token: str | None) -> dict:
    """Shared GitHub repo-metadata GET, used by both the size and
    visibility checks. Raises ``urllib.error.HTTPError``/``URLError`` on
    failure -- callers decide how to interpret each case, since size and
    visibility need different failure handling (fail-open vs
    fail-closed-to-403). ``token``, when given, is sent as a Bearer
    Authorization header; never logged (this function never catches its own
    exceptions, so it never has an opportunity to log one that could embed
    request context).
    """
    url = f"https://api.github.com/repos/{owner}/{name}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=_GITHUB_API_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))  # type: ignore[no-any-return]


def check_github_repo_size(owner: str, name: str, max_mb: int) -> None:
    """Rejects repos over ``max_mb`` (plan/RULES.md sec 14: "reject cleanly
    rather than analyse slowly") by calling the GitHub API for the
    repository's reported size (in KB) BEFORE any clone starts.

    Only applies to github.com repos -- GitLab has an analogous API but it's
    out of scope for this session. If the GitHub API call itself fails for
    any reason other than a clear "this repo doesn't exist" (network error,
    rate limit, timeout), this does NOT block submission: a third-party API
    hiccup must not make Compass itself flaky for repos that would have been
    fine, and the clone step will surface a real problem anyway if the URL
    is genuinely bad. A confirmed size over the limit is the only thing that
    raises here.

    Deliberately anonymous (no token) even for a private repo the caller
    can access -- session 02's ``check_github_repo_visibility`` runs first
    and is what actually resolves a private repo's metadata authenticated;
    by the time this runs, an inaccessible-but-existing private repo simply
    404s here and is treated as "can't confirm size, don't block," same as
    any other lookup hiccup.
    """
    try:
        data = _fetch_github_repo(owner, name, token=None)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"Repository {owner}/{name} was not found on GitHub.") from exc
        logger.warning("GitHub repo-size lookup failed for %s/%s: %r", owner, name, exc)
        return
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("GitHub repo-size lookup failed for %s/%s: %r", owner, name, exc)
        return

    size_kb = data.get("size")
    if not isinstance(size_kb, int):
        return
    size_mb = size_kb / 1024
    if size_mb > max_mb:
        raise ValueError(
            f"Repository is too large to analyze ({size_mb:.0f} MB > {max_mb} MB limit)."
        )


def check_github_repo_visibility(owner: str, name: str, token: str | None) -> bool:
    """Determines whether a github.com repo is private (session 02, Part D).

    Returns ``True``/``False`` for private/public. Raises ``ValueError`` if
    the repo is confirmed not to exist (a 404 that persisted even after an
    authenticated retry, or that needed no retry to confirm). Raises
    ``RepoAccessRequired`` when an anonymous 404 could not be disambiguated
    because no token was supplied, or the authenticated retry itself failed
    for any reason -- fails CLOSED (as "needs auth"), unlike
    ``check_github_repo_size``'s fail-open size check, since the whole point
    here is deciding whether to let an unauthenticated/under-scoped request
    proceed against a repo that might be private.

    Only call this for github.com repos -- GitLab visibility detection is
    out of scope for this session, same as the size check above.
    """
    try:
        data = _fetch_github_repo(owner, name, token=None)
        return bool(data.get("private", False))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            logger.warning("GitHub repo visibility lookup failed for %s/%s: %r", owner, name, exc)
            return False
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("GitHub repo visibility lookup failed for %s/%s: %r", owner, name, exc)
        return False

    # Anonymous lookup 404'd -- ambiguous (doesn't exist, or exists and is
    # private). Only a token lets us tell the two apart.
    if not token:
        raise RepoAccessRequired(f"{owner}/{name} may be private; authentication required.")

    try:
        data = _fetch_github_repo(owner, name, token=token)
        return bool(data.get("private", False))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"Repository {owner}/{name} was not found on GitHub.") from exc
        logger.warning(
            "GitHub repo visibility lookup (authenticated) failed for %s/%s: %r", owner, name, exc
        )
        raise RepoAccessRequired(f"Could not confirm access to {owner}/{name}; try again.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning(
            "GitHub repo visibility lookup (authenticated) failed for %s/%s: %r", owner, name, exc
        )
        raise RepoAccessRequired(f"Could not confirm access to {owner}/{name}; try again.") from exc


def validate_repo_url(url: str) -> None:
    """Reject anything that isn't a plain https URL to an allowlisted host
    whose resolved IPs are all publicly routable.

    v1 guardrail scope only: this blocks the basic SSRF vector (pointing the
    cloner at an internal service via a crafted or DNS-rebound hostname).
    Repo size/clone-time caps and per-IP rate limiting are deliberately out of
    scope here and deferred to the Release-A7 deploy checkpoint.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Repo URL must be a non-empty string.")

    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("Repo URL must use the https scheme.")

    host = parsed.hostname
    if host is None or host.lower() not in ALLOWED_HOSTS:
        raise ValueError(f"Repo host must be one of {sorted(ALLOWED_HOSTS)}.")

    _reject_unsafe_host(host)


def _reject_unsafe_host(host: str) -> None:
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {host!r}.") from exc

    for info in addr_infos:
        raw_ip = info[4][0]
        ip = ipaddress.ip_address(raw_ip)
        if is_unsafe_ip(ip):
            raise ValueError(f"Repo host {host!r} resolves to a disallowed IP address ({raw_ip}).")


def is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
