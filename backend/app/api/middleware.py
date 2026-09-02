"""Request-level hardening and observability middleware (session 16, Parts
C/D) -- registered once in ``app/main.py``. Each is a small, independent
``BaseHTTPMiddleware`` rather than one large class, so a future session can
add/remove/reorder one without touching the others.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.api.request_context import request_id_var

logger = logging.getLogger(__name__)

MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024
"""Session 16, Part C: every real request body in this API is a small JSON
object (``POST /repos``'s ``{"url": "..."}"`` is the largest routinely-sent
one) -- 1 MB is generous headroom for that while still bounding how much an
abusive or broken client can make the process buffer per request."""

REQUEST_TIMEOUT_SECONDS = 30.0
"""Session 16, Part C: a global safety net, not a tuned per-endpoint budget
-- every real handler in this API is either a fast DB read/write or, for
``POST /repos``, hands the actual analysis off to a background task and
returns immediately (Phase 02 progressive reveal). A request that's still
running after 30s is presumed hung, not just slow."""

_SECURITY_HEADERS = {
    # No third-party scripts/styles/frames are ever loaded by this API
    # itself (it serves JSON, not HTML) -- default-src 'none' is achievable
    # and is the strictest useful policy; frame-ancestors 'none' is a
    # belt-and-suspenders duplicate of X-Frame-Options below (both are set
    # since header support for the newer CSP directive isn't universal).
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Frame-Options": "DENY",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Session 16, Part C. This app serves JSON only -- it never renders
    HTML, never loads a third-party script, and is never meant to be
    iframed -- so the strictest form of every one of these headers is
    achievable with zero functional cost (Known Hazard #4 is specifically
    about the FRONTEND's own CSP, a separate concern the frontend build/CDN
    owns; this middleware only ever touches API responses)."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Session 16, Part C: rejects a request whose declared ``Content-Length``
    exceeds ``MAX_REQUEST_BODY_BYTES`` before any handler (or FastAPI's own
    body parsing) ever reads it. Checked from the header alone -- cheap, and
    avoids buffering an oversized body just to measure it; a client that
    lies about ``Content-Length`` and streams more than it declared is a
    narrower residual risk this app-level guard doesn't fully close (a
    reverse-proxy/CDN-level limit is the complete fix, out of scope for this
    process alone)."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_bytes = int(content_length)
            except ValueError:
                declared_bytes = 0
            if declared_bytes > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large."},
                )
        return await call_next(request)


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Session 16, Part C: a global per-request wall-clock ceiling
    (``REQUEST_TIMEOUT_SECONDS``). ``POST /repos`` itself returns almost
    immediately (the real work is a ``BackgroundTasks`` job, not the
    request/response cycle), so this should never fire in normal operation
    -- it exists purely as a safety net against a hung DB call or a stuck
    downstream request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await asyncio.wait_for(call_next(request), timeout=REQUEST_TIMEOUT_SECONDS)
        except TimeoutError:
            return JSONResponse(status_code=504, content={"detail": "Request timed out."})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Session 16, Part D: generates (or reuses an inbound ``X-Request-ID``)
    a per-request id, stores it in ``request_id_var`` for the duration of the
    request (read back by every JSON log line via
    ``app/api/logging_config.py::JsonFormatter``), echoes it on the response,
    and logs one structured line per request with method/path/status/
    duration -- always through the ``logging`` module, so session 01's
    redactor sees it too."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - started) * 1000
            logger.exception(
                "request failed: %s %s (%.1fms)", request.method, request.url.path, duration_ms
            )
            raise
        else:
            duration_ms = (time.monotonic() - started) * 1000
            logger.info(
                "%s %s -> %d (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)


__all__ = [
    "MAX_REQUEST_BODY_BYTES",
    "REQUEST_TIMEOUT_SECONDS",
    "BodySizeLimitMiddleware",
    "RequestContextMiddleware",
    "RequestTimeoutMiddleware",
    "SecurityHeadersMiddleware",
]
