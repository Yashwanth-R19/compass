"""The shared admin-token dependency (session 12, Part D; generalized session
16, Part D) -- guards every ``/internal/...`` endpoint. A shared secret, not a
user session: every caller of these routes is a server-to-server or
console operation (narrative pre-generation, storage/stat inspection), never
something a logged-in product user calls.

An UNCONFIGURED ``COMPASS_ADMIN_TOKEN`` means every admin endpoint is
unreachable (503), never silently open -- this must not accept every request
the moment someone forgets to set it in production.

Originally defined only in ``app/api/narrative.py`` (session 12); moved here
session 16 once a second and third admin endpoint (``/internal/storage``,
``/internal/stats``) needed the identical check -- narrative.py now imports
this instead of keeping its own copy.
"""

import hmac

from fastapi import Header, HTTPException

from app.config import settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.COMPASS_ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin endpoints are not configured.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, settings.COMPASS_ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


__all__ = ["require_admin_token"]
