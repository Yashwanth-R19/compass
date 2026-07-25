import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_HOSTS = {"github.com", "gitlab.com"}


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
