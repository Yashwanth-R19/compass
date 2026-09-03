"""In-memory rate limiting for ``POST /repos`` (session 02, Part F).

**This limiter is correct for exactly one process.** Every bucket lives in a
plain dict guarded by a single lock, in this process's memory. If Compass is
ever deployed across more than one instance (Render's free tier never runs
more than one, but a paid, horizontally-scaled deployment would), each
instance enforces its own independent limit -- the effective rate limit
becomes ``configured limit * instance count``, silently. Move this to Redis
or Postgres before scaling beyond one process.

Two things are enforced, both only on ``POST /repos`` (read endpoints are
not rate-limited by this module):

- **Per-key submission quota** (``TokenBucketLimiter``): anonymous requests
  keyed by client IP, authenticated requests keyed by user id, each with
  separate hourly and daily caps (plan/RULES.md-analogous, values in
  ``app/config.py`` so they're tunable without a code change).
- **Global concurrency cap** (``check_concurrency_cap``): at most
  ``COMPASS_MAX_CONCURRENT_RUNS`` analysis runs may be ``running`` across
  the whole system at once, checked directly against the ``analysis_runs``
  table (real DB state, not an in-memory count -- this half of the module
  has no single-process caveat). Excess submissions are rejected outright
  with a 429 and a ``Retry-After`` header -- there is deliberately no queue
  and no ``queued`` run status; a rejected submission can simply be
  resubmitted once a slot frees up.
"""

import threading
import time
from collections import Counter
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AnalysisRun, AnalysisRunStatus, Repo, User

# Session 16, Part D: process-lifetime rejection counters, surfaced by
# GET /internal/stats. Same single-process caveat as every other piece of
# state in this module (the docstring above already covers why) -- a counter
# reset to zero on every deploy is an accepted, documented limitation of a
# free-tier, single-instance deployment, not a bug.
_rejection_counts: Counter[str] = Counter()
_rejection_lock = threading.Lock()


def _record_rejection(kind: str) -> None:
    with _rejection_lock:
        _rejection_counts[kind] += 1


def get_rejection_counts() -> dict[str, int]:
    with _rejection_lock:
        return dict(_rejection_counts)


@dataclass
class _WindowState:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    """A token bucket over TWO windows at once (e.g. "N per hour" AND "M per
    day") -- a key may consume a token only when BOTH windows currently have
    capacity, and consumption is atomic across both (a request rejected by
    the daily window never partially drains the hourly one).
    """

    def __init__(self, per_hour: int, per_day: int) -> None:
        self._per_hour = per_hour
        self._per_day = per_day
        self._hour_state: dict[str, _WindowState] = {}
        self._day_state: dict[str, _WindowState] = {}
        self._lock = threading.Lock()

    def _refill(
        self,
        state: dict[str, _WindowState],
        key: str,
        capacity: int,
        window_seconds: float,
        now: float,
    ) -> _WindowState:
        entry = state.get(key)
        if entry is None:
            entry = _WindowState(tokens=float(capacity), last_refill=now)
            state[key] = entry
            return entry
        elapsed = now - entry.last_refill
        if elapsed > 0:
            rate = capacity / window_seconds
            entry.tokens = min(float(capacity), entry.tokens + elapsed * rate)
            entry.last_refill = now
        return entry

    def try_consume(self, key: str) -> tuple[bool, float]:
        """Returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds``
        is 0.0 when allowed, else the time until whichever window (hourly or
        daily) is the binding constraint would next have a free token."""
        now = time.monotonic()
        with self._lock:
            hour_entry = self._refill(self._hour_state, key, self._per_hour, 3600.0, now)
            day_entry = self._refill(self._day_state, key, self._per_day, 86400.0, now)

            if hour_entry.tokens >= 1.0 and day_entry.tokens >= 1.0:
                hour_entry.tokens -= 1.0
                day_entry.tokens -= 1.0
                return True, 0.0

            retry_after = 0.0
            if hour_entry.tokens < 1.0:
                rate = self._per_hour / 3600.0
                retry_after = max(retry_after, (1.0 - hour_entry.tokens) / rate)
            if day_entry.tokens < 1.0:
                rate = self._per_day / 86400.0
                retry_after = max(retry_after, (1.0 - day_entry.tokens) / rate)
            return False, retry_after


_anon_limiter = TokenBucketLimiter(
    per_hour=settings.COMPASS_RATE_LIMIT_ANON_PER_HOUR,
    per_day=settings.COMPASS_RATE_LIMIT_ANON_PER_DAY,
)
_user_limiter = TokenBucketLimiter(
    per_hour=settings.COMPASS_RATE_LIMIT_USER_PER_HOUR,
    per_day=settings.COMPASS_RATE_LIMIT_USER_PER_DAY,
)

# Session 12: a SEPARATE bucket pair for narrative GENERATION specifically
# (app/api/narrative.py) -- "how many repos can you submit" and "how many
# LLM calls can you trigger" are different resources. Only charged on the
# path that would actually call a provider; a cache hit never touches this.
_narrative_anon_limiter = TokenBucketLimiter(
    per_hour=settings.COMPASS_NARRATIVE_RATE_LIMIT_ANON_PER_HOUR,
    per_day=settings.COMPASS_NARRATIVE_RATE_LIMIT_ANON_PER_DAY,
)
_narrative_user_limiter = TokenBucketLimiter(
    per_hour=settings.COMPASS_NARRATIVE_RATE_LIMIT_USER_PER_HOUR,
    per_day=settings.COMPASS_NARRATIVE_RATE_LIMIT_USER_PER_DAY,
)


def get_client_ip(request: Request) -> str:
    """The first entry of ``X-Forwarded-For``, or the direct connection's
    address as a local-dev fallback.

    This is only safe to trust because Render (this project's deployment
    target, DEPLOY.md) is a TRUSTED proxy that OVERWRITES ``X-Forwarded-For``
    with the real client address rather than appending to whatever a client
    sent -- behind an untrusted proxy (or with no proxy at all, where a
    client could set this header directly), taking it at face value would
    let anyone forge their way past IP-based rate limiting.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def check_analysis_rate_limit(request: Request, user: User | None) -> None:
    """Raises HTTP 429 if this caller's submission quota (anonymous-by-IP or
    authenticated-by-user, app/config.py's COMPASS_RATE_LIMIT_* settings) is
    exhausted. Call this from ``POST /repos`` only."""
    if user is not None:
        key = f"user:{user.id}"
        limiter = _user_limiter
    else:
        key = f"ip:{get_client_ip(request)}"
        limiter = _anon_limiter

    allowed, retry_after = limiter.try_consume(key)
    if not allowed:
        _record_rejection("analysis_rate_limit")
        retry_after_seconds = int(retry_after) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after_seconds} seconds.",
            headers={"Retry-After": str(retry_after_seconds)},
        )


def check_narrative_rate_limit(request: Request, user: User | None) -> None:
    """Raises HTTP 429 if this caller's narrative-GENERATION quota is
    exhausted. Call this only from the code path that is about to make a
    live provider call -- a cache hit costs nothing and must never be rate-
    limited (app/api/narrative.py)."""
    if user is not None:
        key = f"user:{user.id}"
        limiter = _narrative_user_limiter
    else:
        key = f"ip:{get_client_ip(request)}"
        limiter = _narrative_anon_limiter

    allowed, retry_after = limiter.try_consume(key)
    if not allowed:
        _record_rejection("narrative_rate_limit")
        retry_after_seconds = int(retry_after) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Narrative generation rate limit exceeded. Try again in {retry_after_seconds} seconds.",
            headers={"Retry-After": str(retry_after_seconds)},
        )


MAX_REPOS_PER_USER = 25
"""Session 16, Part C: a per-user ceiling on analysed repositories, separate
from every rate limit above (those bound how FAST a user can submit; this
bounds how MANY repos they can own at once, which is what actually drives
this user's share of storage). Checked only when the submission would create
a genuinely NEW ``repos`` row -- re-analysing an already-owned repo never
counts as a new one against this cap, since it doesn't add a row."""


def check_user_repo_cap(user: User, db: Session) -> None:
    """Raises HTTP 409 (a real conflict the caller can resolve, not a
    transient rate limit -- deliberately not 429) when ``user`` already owns
    ``MAX_REPOS_PER_USER`` repositories. The error message points at
    ``DELETE /repos/{id}`` (app/api/repos.py), which frees a slot by fully
    removing one of the user's own repositories -- the "clear UI for
    choosing which" the session prompt asks for lives on the frontend's
    dashboard, backed by this same endpoint."""
    owned = db.scalar(select(func.count()).select_from(Repo).where(Repo.owner_user_id == user.id))
    if (owned or 0) >= MAX_REPOS_PER_USER:
        _record_rejection("user_repo_cap")
        raise HTTPException(
            status_code=409,
            detail=(
                f"You've reached the {MAX_REPOS_PER_USER}-repository limit. "
                "Remove one from your dashboard to analyze another."
            ),
        )


def check_concurrency_cap(db: Session) -> None:
    """Raises HTTP 429 if ``COMPASS_MAX_CONCURRENT_RUNS`` analysis runs are
    already ``running`` system-wide. Excess submissions are rejected, not
    queued -- there is no run queue in this codebase."""
    running = (
        db.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(AnalysisRun.status == AnalysisRunStatus.running)
        )
        or 0
    )
    if running >= settings.COMPASS_MAX_CONCURRENT_RUNS:
        _record_rejection("concurrency_cap")
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many analyses are running right now "
                f"({running}/{settings.COMPASS_MAX_CONCURRENT_RUNS}). Try again shortly."
            ),
            headers={"Retry-After": "30"},
        )


__all__ = [
    "MAX_REPOS_PER_USER",
    "TokenBucketLimiter",
    "check_analysis_rate_limit",
    "check_concurrency_cap",
    "check_narrative_rate_limit",
    "check_user_repo_cap",
    "get_client_ip",
    "get_rejection_counts",
]
