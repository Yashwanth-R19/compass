import pytest
from fastapi import HTTPException

from app.api import limits as limits_module
from app.api.limits import TokenBucketLimiter, check_concurrency_cap
from app.db.models import AnalysisRun, AnalysisRunStatus, Repo, RepoStatus


def test_bucket_allows_up_to_capacity_then_rejects():
    limiter = TokenBucketLimiter(per_hour=3, per_day=100)
    key = "isolated-key-1"

    for _ in range(3):
        allowed, _ = limiter.try_consume(key)
        assert allowed is True

    allowed, retry_after = limiter.try_consume(key)
    assert allowed is False
    assert retry_after > 0


def test_bucket_refills_over_time():
    limiter = TokenBucketLimiter(per_hour=3600, per_day=100000)  # 1 token/second
    key = "isolated-key-2"

    allowed, _ = limiter.try_consume(key)
    assert allowed is True

    # Drain directly instead of looping 3600 times to exercise the same path.
    entry = limiter._hour_state[key]
    entry.tokens = 0.0

    allowed, retry_after = limiter.try_consume(key)
    assert allowed is False
    assert retry_after == pytest.approx(1.0, abs=0.1)

    # Rewind the refill clock -- equivalent to "more than a second passed".
    entry.last_refill -= 2.0
    allowed, _ = limiter.try_consume(key)
    assert allowed is True


def test_daily_cap_binds_even_when_hourly_has_room():
    limiter = TokenBucketLimiter(per_hour=1000, per_day=2)
    key = "isolated-key-3"

    assert limiter.try_consume(key)[0] is True
    assert limiter.try_consume(key)[0] is True

    allowed, retry_after = limiter.try_consume(key)
    assert allowed is False
    assert retry_after > 0


def test_keys_are_isolated_from_each_other():
    limiter = TokenBucketLimiter(per_hour=1, per_day=10)

    assert limiter.try_consume("key-a")[0] is True
    assert limiter.try_consume("key-a")[0] is False
    # A different key has its own untouched bucket.
    assert limiter.try_consume("key-b")[0] is True


def test_concurrency_cap_returns_429_with_a_retry_hint(db_session, monkeypatch):
    monkeypatch.setattr(limits_module.settings, "COMPASS_MAX_CONCURRENT_RUNS", 1)

    repo = Repo(
        url="https://github.com/o/concurrency",
        owner="o",
        name="concurrency",
        status=RepoStatus.ready,
    )
    db_session.add(repo)
    db_session.flush()
    run = AnalysisRun(repo_id=repo.id, status=AnalysisRunStatus.running, head_sha="deadbeef")
    db_session.add(run)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        check_concurrency_cap(db_session)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_concurrency_cap_allows_submission_under_the_limit(db_session, monkeypatch):
    monkeypatch.setattr(limits_module.settings, "COMPASS_MAX_CONCURRENT_RUNS", 3)

    check_concurrency_cap(db_session)  # no running runs at all -- must not raise
