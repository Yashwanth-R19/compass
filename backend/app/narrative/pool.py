"""A rotating pool of free-tier LLM API keys (session 12, Part A).

**This pool is correct for exactly one process**, same caveat as
``app/api/limits.py``'s token-bucket rate limiter: every key's health state
(consecutive failures, cooldown, last error kind) lives in a plain list
guarded by one ``threading.Lock``, in this process's memory. If Compass is
ever deployed across more than one instance, each instance tracks its own
independent view of which keys are cold -- move this to Redis/Postgres
before scaling beyond one process. Render's free tier never runs more than
one instance, so this is fine today.

**The system must work correctly with zero keys configured** -- the default
for anyone self-hosting Compass without paying for an LLM key.
``COMPASS_GEMINI_KEYS``/``COMPASS_GROQ_KEYS`` (comma-separated, per
provider) are read once at import time; an absent or empty variable simply
means that provider contributes no keys. ``get_key()`` returning ``None``
(either because there are no keys at all, or because every configured key is
currently cooling down) is a normal, expected outcome the caller
(``generate.py``) turns into an honest "narrative unavailable" -- never an
exception, never a retry storm.

**A key value must never be logged, returned by any API, or included in an
error message.** Every configured key is fed into
``app/jobs/log_redaction.py``'s scrub list at pool-construction time (see
``build_pool_from_settings`` below) -- this is in addition to, not instead
of, that module's existing whole-blob match on the ``COMPASS_*_KEYS`` env
var's raw value (its name already contains the "KEY" marker).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

from app.config import settings
from app.jobs.log_redaction import add_secret_values

FailureKind = Literal["rate_limit", "auth", "server", "timeout"]

# Priority order: try every Groq key before falling to Gemini. A plain
# infra choice (not a locked/heuristic PRODUCT number, RULES.md sec 3), and
# NOT the original order -- Gemini was tried first through session 12, on
# no stronger basis than being named first in that session's prompt.
# Session 4 flipped it after live-testing both against this app's actual
# narrative prompt: `get_key()` returns the FIRST provider in this tuple
# that has any non-cooling key, every single call, and tries every one of
# that provider's keys (round-robin) before ever reaching the next provider
# -- so with ~10 Gemini keys configured, Gemini being first meant a whole
# generation's `MAX_KEY_ATTEMPTS` budget could be spent on a single flaky
# provider before Groq (confirmed reliable once properly configured, see
# providers.py) ever got a turn.
PROVIDER_PRIORITY: tuple[str, ...] = ("groq", "gemini")

# Cooldown policy (Part A):
#   rate_limit -> exponential backoff from 60s, doubling per consecutive
#                 failure, capped at 1 hour.
#   auth       -> 24 hours (a revoked/invalid key will not recover in a
#                 minute -- no point retrying it soon).
#   server / timeout -> a flat 30s (a transient blip, worth retrying soon).
RATE_LIMIT_BASE_COOLDOWN_SECONDS = 60.0
RATE_LIMIT_MAX_COOLDOWN_SECONDS = 3600.0
AUTH_COOLDOWN_SECONDS = 24 * 3600.0
TRANSIENT_COOLDOWN_SECONDS = 30.0


@dataclass
class ProviderKey:
    """One configured API key plus its mutable health state. ``key`` is the
    raw secret value -- callers must never log or return this object's
    ``key`` field; only ``provider`` (a plain label) is ever safe to
    surface."""

    provider: str
    key: str
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_error_kind: FailureKind | None = None

    def is_available(self, now: float) -> bool:
        return now >= self.cooldown_until


class KeyPool:
    """The pure, independently-testable pool -- takes an explicit
    ``{provider: [key, ...]}`` mapping rather than reading settings itself,
    so tests can construct one with whatever keys/providers they need
    without touching environment variables. ``build_pool_from_settings()``
    below is the production singleton built from config."""

    def __init__(self, keys_by_provider: dict[str, list[str]]) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, list[ProviderKey]] = {
            provider: [ProviderKey(provider=provider, key=k) for k in keys]
            for provider, keys in keys_by_provider.items()
            if keys
        }
        self._round_robin_index: dict[str, int] = dict.fromkeys(self._keys, 0)

    def has_any_keys(self) -> bool:
        return any(self._keys.values())

    def get_key(self) -> ProviderKey | None:
        """The healthiest available key: providers are tried in
        ``PROVIDER_PRIORITY`` order, and within a provider, keys are
        round-robined (so a single key isn't burned first every time) and
        skipped while they're in cooldown. Returns ``None`` when no
        provider has an available key right now -- exhaustion, not an
        error."""
        now = time.monotonic()
        with self._lock:
            for provider in PROVIDER_PRIORITY:
                candidates = self._keys.get(provider)
                if not candidates:
                    continue
                count = len(candidates)
                start = self._round_robin_index.get(provider, 0)
                for offset in range(count):
                    idx = (start + offset) % count
                    candidate = candidates[idx]
                    if candidate.is_available(now):
                        self._round_robin_index[provider] = (idx + 1) % count
                        return candidate
            return None

    def report_failure(self, key: ProviderKey, kind: FailureKind) -> None:
        with self._lock:
            key.consecutive_failures += 1
            key.last_error_kind = kind
            now = time.monotonic()
            if kind == "rate_limit":
                cooldown = min(
                    RATE_LIMIT_BASE_COOLDOWN_SECONDS * (2 ** (key.consecutive_failures - 1)),
                    RATE_LIMIT_MAX_COOLDOWN_SECONDS,
                )
            elif kind == "auth":
                cooldown = AUTH_COOLDOWN_SECONDS
            else:
                cooldown = TRANSIENT_COOLDOWN_SECONDS
            key.cooldown_until = now + cooldown

    def report_success(self, key: ProviderKey) -> None:
        with self._lock:
            key.consecutive_failures = 0
            key.cooldown_until = 0.0
            key.last_error_kind = None


def _parse_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def build_pool_from_settings() -> KeyPool:
    keys_by_provider = {
        "gemini": _parse_keys(settings.COMPASS_GEMINI_KEYS),
        "groq": _parse_keys(settings.COMPASS_GROQ_KEYS),
    }
    all_keys = [k for keys in keys_by_provider.values() for k in keys]
    if all_keys:
        add_secret_values(all_keys)
    return KeyPool(keys_by_provider)


# The production singleton -- every FastAPI request goes through these
# module-level functions, not through KeyPool directly. Tests exercise
# KeyPool itself with their own key sets instead of monkeypatching settings
# and re-importing this module.
_pool = build_pool_from_settings()


def has_any_keys() -> bool:
    return _pool.has_any_keys()


def get_key() -> ProviderKey | None:
    return _pool.get_key()


def report_failure(key: ProviderKey, kind: FailureKind) -> None:
    _pool.report_failure(key, kind)


def report_success(key: ProviderKey) -> None:
    _pool.report_success(key)


__all__ = [
    "AUTH_COOLDOWN_SECONDS",
    "PROVIDER_PRIORITY",
    "RATE_LIMIT_BASE_COOLDOWN_SECONDS",
    "RATE_LIMIT_MAX_COOLDOWN_SECONDS",
    "TRANSIENT_COOLDOWN_SECONDS",
    "FailureKind",
    "KeyPool",
    "ProviderKey",
    "build_pool_from_settings",
    "get_key",
    "has_any_keys",
    "report_failure",
    "report_success",
]
