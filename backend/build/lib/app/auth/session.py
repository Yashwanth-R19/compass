"""The httpOnly session cookie's JWT (session 02, Part C).

Distinct from ``app/auth/crypto.py``: that module encrypts a GitHub access
token for confidentiality (Fernet, symmetric, reversible by design so the
cloner can use it). This module signs a small claims payload -- "this
browser is authenticated as user X, until this time" -- for integrity only
(HS256); there's nothing in the payload worth encrypting, just a user id and
an expiry.

**SameSite decision (see CLAUDE.md's auth-architecture section for the full
writeup):** the frontend (Vercel) and API (Render) are different sites, so a
``SameSite=Lax`` cookie set by the API is never sent on the cross-site
``fetch(..., {credentials: "include"})`` calls the frontend makes -- Lax
only allows a cookie on a top-level GET navigation, not a subrequest. This
session cookie is therefore issued ``SameSite=None; Secure``, and CSRF
protection for the state-changing endpoints that accept it rests on (a) the
OAuth `state` parameter during login (a Lax-cookie, top-level-GET flow,
unaffected by this) and (b) the API never accepting a state-changing
operation over GET.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings

SESSION_COOKIE_NAME = "compass_session"
SESSION_TTL = timedelta(days=7)
_ALGORITHM = "HS256"


def create_session_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + SESSION_TTL}
    return jwt.encode(payload, settings.COMPASS_JWT_SECRET, algorithm=_ALGORITHM)


def decode_session_token(token: str) -> uuid.UUID | None:
    """Returns the user id encoded in ``token`` if it's validly signed and
    unexpired, else ``None``. Never raises -- every caller (app/auth/deps.py)
    only cares "authenticated or not," not why a bad token failed."""
    try:
        payload = jwt.decode(token, settings.COMPASS_JWT_SECRET, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None

    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None
    try:
        return uuid.UUID(sub)
    except ValueError:
        return None


__all__ = ["SESSION_COOKIE_NAME", "SESSION_TTL", "create_session_token", "decode_session_token"]
