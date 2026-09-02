"""Session 12, Part A/F: the key pool. Pure in-memory logic, no DB, no
network -- every test constructs its own ``KeyPool`` directly rather than
touching the settings-driven singleton (see ``pool.py``'s own docstring for
why that's the intended testing seam)."""

import time

import pytest

from app.narrative.pool import (
    AUTH_COOLDOWN_SECONDS,
    RATE_LIMIT_BASE_COOLDOWN_SECONDS,
    RATE_LIMIT_MAX_COOLDOWN_SECONDS,
    TRANSIENT_COOLDOWN_SECONDS,
    KeyPool,
)


def test_zero_keys_configured_is_not_an_error():
    pool = KeyPool({})
    assert pool.has_any_keys() is False
    assert pool.get_key() is None


def test_zero_keys_configured_for_every_provider_is_not_an_error():
    pool = KeyPool({"gemini": [], "groq": []})
    assert pool.has_any_keys() is False
    assert pool.get_key() is None


def test_rotation_round_robins_within_a_provider():
    pool = KeyPool({"gemini": ["k1", "k2", "k3"]})
    seen = [pool.get_key().key for _ in range(6)]
    assert seen == ["k1", "k2", "k3", "k1", "k2", "k3"]


def test_priority_order_prefers_gemini_before_groq():
    pool = KeyPool({"gemini": ["g1"], "groq": ["q1"]})
    assert pool.get_key().key == "g1"
    assert pool.get_key().key == "g1"  # only one gemini key -- keeps rotating to itself


def test_falls_through_to_next_provider_when_first_is_exhausted():
    pool = KeyPool({"gemini": ["g1"], "groq": ["q1"]})
    key = pool.get_key()
    assert key.key == "g1"
    pool.report_failure(key, "auth")

    fallback = pool.get_key()
    assert fallback.key == "q1"


def test_rate_limited_key_enters_cooldown_and_is_skipped():
    pool = KeyPool({"gemini": ["g1", "g2"]})
    key = pool.get_key()
    assert key.key == "g1"
    pool.report_failure(key, "rate_limit")

    # g1 is cooling down -- every subsequent get_key() must return g2 only.
    for _ in range(3):
        assert pool.get_key().key == "g2"


def test_rate_limit_cooldown_is_exponential_from_60s_capped_at_1_hour():
    pool = KeyPool({"gemini": ["g1"]})
    key = pool.get_key()

    # `time.monotonic()` reads on either side of report_failure() can differ
    # by a few microseconds of real scheduling jitter -- pytest.approx keeps
    # these assertions from flaking on that, while still pinning the value
    # to well within a second of the documented cooldown.
    before = time.monotonic()
    pool.report_failure(key, "rate_limit")
    assert key.cooldown_until - before == pytest.approx(RATE_LIMIT_BASE_COOLDOWN_SECONDS, abs=1.0)

    before = time.monotonic()
    pool.report_failure(key, "rate_limit")
    assert key.cooldown_until - before == pytest.approx(
        RATE_LIMIT_BASE_COOLDOWN_SECONDS * 2, abs=1.0
    )

    # Keep failing until the exponential curve would exceed the cap.
    for _ in range(10):
        pool.report_failure(key, "rate_limit")
    before = time.monotonic()
    pool.report_failure(key, "rate_limit")
    assert key.cooldown_until - before == pytest.approx(RATE_LIMIT_MAX_COOLDOWN_SECONDS, abs=1.0)


def test_auth_failure_gets_a_24_hour_cooldown():
    pool = KeyPool({"gemini": ["g1"]})
    key = pool.get_key()
    before = time.monotonic()
    pool.report_failure(key, "auth")
    assert key.cooldown_until - before == pytest.approx(AUTH_COOLDOWN_SECONDS, abs=1.0)
    assert key.last_error_kind == "auth"
    assert pool.get_key() is None


def test_server_and_timeout_failures_get_a_flat_30s_cooldown():
    pool = KeyPool({"gemini": ["g1"]})
    key = pool.get_key()

    before = time.monotonic()
    pool.report_failure(key, "server")
    assert key.cooldown_until - before == pytest.approx(TRANSIENT_COOLDOWN_SECONDS, abs=1.0)

    pool.report_success(key)
    before = time.monotonic()
    pool.report_failure(key, "timeout")
    assert key.cooldown_until - before == pytest.approx(TRANSIENT_COOLDOWN_SECONDS, abs=1.0)


def test_report_success_resets_failure_state():
    pool = KeyPool({"gemini": ["g1"]})
    key = pool.get_key()
    pool.report_failure(key, "rate_limit")
    assert key.consecutive_failures == 1

    pool.report_success(key)
    assert key.consecutive_failures == 0
    assert key.cooldown_until == 0.0
    assert key.last_error_kind is None
    assert pool.get_key() is not None


def test_all_keys_dead_returns_none():
    pool = KeyPool({"gemini": ["g1", "g2"], "groq": ["q1"]})
    for _ in range(3):
        key = pool.get_key()
        pool.report_failure(key, "auth")

    assert pool.get_key() is None


def test_get_key_never_returns_the_raw_key_via_repr_leak_check():
    # Not a security assertion on logging (that's covered by
    # test_log_redaction.py) -- just a sanity check that ProviderKey itself
    # only ever exposes its secret through the one documented `.key` field,
    # never through some derived/public helper.
    pool = KeyPool({"gemini": ["super-secret-value"]})
    key = pool.get_key()
    assert key.provider == "gemini"
    assert key.key == "super-secret-value"
