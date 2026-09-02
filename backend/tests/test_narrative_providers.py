"""Session 12, Part A/F: the per-provider HTTP adapters. Every test mocks
``httpx.post`` -- no real network call is ever made from this file."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.narrative.pool import ProviderKey
from app.narrative.providers import ProviderError, generate


def _fake_response(status_code: int, body: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


GEMINI_KEY = ProviderKey(provider="gemini", key="fake-gemini-key")
GROQ_KEY = ProviderKey(provider="groq", key="fake-groq-key")


def test_gemini_success_returns_text():
    body = {"candidates": [{"content": {"parts": [{"text": "Some grounded prose."}]}}]}
    with patch("httpx.post", return_value=_fake_response(200, body)):
        text = generate("prompt", GEMINI_KEY, 100)
    assert text == "Some grounded prose."


def test_gemini_429_maps_to_rate_limit():
    with (
        patch("httpx.post", return_value=_fake_response(429, {})),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "rate_limit"


def test_gemini_401_maps_to_auth():
    with (
        patch("httpx.post", return_value=_fake_response(401, {})),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "auth"


def test_gemini_404_unknown_model_maps_to_auth_not_server():
    """Known Hazard #3: a renamed/retired free-tier model must cool down
    long (auth), not retry in a tight loop (server)."""
    with (
        patch("httpx.post", return_value=_fake_response(404, {})),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "auth"


def test_gemini_500_maps_to_server():
    with (
        patch("httpx.post", return_value=_fake_response(500, {})),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "server"


def test_gemini_200_with_quota_error_body_maps_to_rate_limit():
    """Known Hazard #4: some providers answer 200 with an error object
    instead of a non-2xx status -- the body must be read, not just trusted
    because the status was 2xx."""
    body = {"error": {"message": "Quota exceeded for this project", "code": "RESOURCE_EXHAUSTED"}}
    with (
        patch("httpx.post", return_value=_fake_response(200, body)),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "rate_limit"


def test_gemini_200_with_invalid_api_key_body_maps_to_auth():
    body = {"error": {"message": "API key not valid. Please pass a valid API key."}}
    with (
        patch("httpx.post", return_value=_fake_response(200, body)),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "auth"


def test_gemini_blocked_response_shape_maps_to_server_not_a_crash():
    body = {"candidates": [{"finishReason": "SAFETY"}]}
    with (
        patch("httpx.post", return_value=_fake_response(200, body)),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "server"


def test_gemini_timeout_maps_to_timeout():
    with (
        patch("httpx.post", side_effect=httpx.TimeoutException("timed out")),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert exc_info.value.kind == "timeout"


def test_groq_success_returns_text_and_sends_bearer_auth():
    body = {"choices": [{"message": {"content": "Groq prose."}}]}
    with patch("httpx.post", return_value=_fake_response(200, body)) as mock_post:
        text = generate("prompt", GROQ_KEY, 100)
    assert text == "Groq prose."
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer fake-groq-key"


def test_groq_429_maps_to_rate_limit():
    body = {"error": {"message": "Rate limit reached for requests", "type": "requests"}}
    with (
        patch("httpx.post", return_value=_fake_response(429, body)),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GROQ_KEY, 100)
    assert exc_info.value.kind == "rate_limit"


def test_unknown_provider_raises_auth_error():
    bogus = ProviderKey(provider="not-a-real-provider", key="x")
    with pytest.raises(ProviderError) as exc_info:
        generate("prompt", bogus, 100)
    assert exc_info.value.kind == "auth"


def test_no_key_value_ever_appears_in_a_raised_error_message():
    with (
        patch("httpx.post", return_value=_fake_response(401, {})),
        pytest.raises(ProviderError) as exc_info,
    ):
        generate("prompt", GEMINI_KEY, 100)
    assert "fake-gemini-key" not in str(exc_info.value)
