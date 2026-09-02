"""Thin per-provider HTTP adapters (session 12, Part A) -- plain JSON POSTs
over ``httpx``, deliberately not a provider SDK ("two SDKs is two dependency
trees for no benefit," per the session prompt). Each adapter maps its own
provider's HTTP status codes AND response bodies onto the four failure
kinds ``app/narrative/pool.py`` understands (``rate_limit`` / ``auth`` /
``server`` / ``timeout``) via ``ProviderError``.

**Known Hazard #4 (rate-limit responses vary):** some providers return a
plain 429; some return HTTP 200 with an error object in the body. Every
adapter here checks the response BODY for an error, regardless of status
code, before trusting a 2xx as success -- an unrecognised body-level error is
classified by keyword-matching its own message text
(``_classify_error_text``), never assumed to be a real result.

**Known Hazard #3 (models/endpoints drift on free tiers):** the model name
is read from config (``app/config.py``), never hardcoded here, and a
response indicating "model not found"/"model not supported" is classified as
``auth`` rather than ``server`` -- an unknown-model failure will never
self-heal by retrying soon, so it must cool the key down for a long time
(24h) exactly like a bad credential does, or the pool would hammer a
misconfigured model name in a tight loop forever.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.narrative.pool import FailureKind, ProviderKey

# Session prompt, Part A: "Use httpx with a hard 20-second timeout."
REQUEST_TIMEOUT_SECONDS = 20.0

DEFAULT_MAX_TOKENS = 220


class ProviderError(Exception):
    """Raised by every adapter for any failure -- transport-level or a
    body-level error object -- carrying the ``FailureKind`` the caller
    reports to the pool. ``str(exc)`` is safe to log (it never contains the
    request's own API key), but callers should still run it through
    ``app/jobs/log_redaction.py::redact`` before logging, as a second layer
    of defense against a future provider response body ever echoing a key
    back."""

    def __init__(self, kind: FailureKind, message: str) -> None:
        super().__init__(message)
        self.kind: FailureKind = kind


_RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "quota",
    "resource_exhausted",
    "too many requests",
)
_AUTH_MARKERS = (
    "api key",
    "api_key",
    "invalid_api_key",
    "unauthorized",
    "unauthenticated",
    "permission_denied",
    "forbidden",
    "model not found",
    "does not exist",
    "not found for api version",
    "invalid model",
)


def _classify_error_text(text: str) -> FailureKind:
    lowered = text.lower()
    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return "rate_limit"
    if any(marker in lowered for marker in _AUTH_MARKERS):
        return "auth"
    return "server"


def _classify_status(status_code: int) -> FailureKind:
    if status_code == 429:
        return "rate_limit"
    # 400/401/403/404 are all "something about the request/credentials/model
    # is wrong" -- none of these will resolve themselves by retrying soon,
    # so all four map to the long (24h) `auth` cooldown (Known Hazard #3).
    if status_code in (400, 401, 403, 404):
        return "auth"
    return "server"


def _post_json(url: str, *, json_body: dict, headers: dict[str, str] | None = None) -> dict:
    try:
        response = httpx.post(url, json=json_body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.TimeoutException as exc:
        raise ProviderError("timeout", "request timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderError("server", f"transport error: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise ProviderError(_classify_status(response.status_code), f"HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError("server", "response was not valid JSON") from exc

    # Known Hazard #4: some providers answer 200 with an error object rather
    # than a non-2xx status. Any dict-shaped "error" key at the top level is
    # treated as a real failure, classified from its own text.
    error = data.get("error") if isinstance(data, dict) else None
    if error is not None:
        message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        raise ProviderError(_classify_error_text(message), message)

    return data


def _generate_gemini(prompt: str, key: ProviderKey, max_tokens: int) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.COMPASS_GEMINI_MODEL}:generateContent?key={key.key}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
    }
    data = _post_json(url, json_body=body)
    try:
        candidates = data["candidates"]
        text = candidates[0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        # A candidate can also be blocked (finishReason == "SAFETY", no
        # `content` at all) -- that's a real, if unusual, response shape,
        # not a transport failure, so it maps to `server` (retry a
        # different key soon) rather than `auth` (this key isn't bad).
        raise ProviderError("server", "unexpected response shape (possibly blocked)") from exc
    if not isinstance(text, str):
        raise ProviderError("server", "response text was not a string")
    return text


def _generate_groq(prompt: str, key: ProviderKey, max_tokens: int) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    body = {
        "model": settings.COMPASS_GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    headers = {"Authorization": f"Bearer {key.key}"}
    data = _post_json(url, json_body=body, headers=headers)
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("server", "unexpected response shape") from exc
    if not isinstance(text, str):
        raise ProviderError("server", "response content was not a string")
    return text


_ADAPTERS = {
    "gemini": _generate_gemini,
    "groq": _generate_groq,
}


def generate(prompt: str, key: ProviderKey, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Sends ``prompt`` (already containing both the system instructions and
    the fact-pack data -- see ``generate.py::build_prompt``) to whichever
    provider ``key`` belongs to. Raises ``ProviderError`` on any failure;
    never returns an empty/partial result silently."""
    adapter = _ADAPTERS.get(key.provider)
    if adapter is None:
        raise ProviderError("auth", f"no adapter registered for provider {key.provider!r}")
    return adapter(prompt, key, max_tokens)


__all__ = ["DEFAULT_MAX_TOKENS", "ProviderError", "generate"]
