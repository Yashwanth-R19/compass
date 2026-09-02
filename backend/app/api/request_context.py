"""A per-request id, threaded through logging (session 16, Part D) --
``app/api/middleware.py::RequestContextMiddleware`` sets it at the top of
every request; ``app/api/logging_config.py``'s JSON formatter reads it back
on every log record emitted while that request is in flight. A
``contextvars.ContextVar`` is what makes this work correctly under
``asyncio`` (unlike ``threading.local``, which a single-threaded async event
loop would leave shared across every concurrently in-flight request).
"""

import contextvars

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

__all__ = ["request_id_var"]
