"""Structured JSON logging (session 16, Part D) -- every log line the API
process emits, one JSON object per line (timestamp, level, logger name,
message, and the in-flight request id when there is one), always passed
through session 01's ``RedactingFilter`` first. ``configure_logging()`` is
the one place this is wired up; call it once, at process startup
(``app/main.py``), before any request is served.
"""

import json
import logging
from datetime import UTC, datetime

from app.api.request_context import request_id_var
from app.jobs.log_redaction import install_log_redaction


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Replaces the root logger's handlers with a single JSON-formatted
    stream handler, and installs ``RedactingFilter`` on the root LOGGER
    itself (a logger-level filter, distinct from ``root.handlers`` -- it runs
    before any handler, including the one this function just added, ever
    sees the record, so every line is scrubbed regardless of handler order).
    Safe to call more than once: ``root.handlers.clear()`` only touches
    handlers, and ``install_log_redaction`` is independently idempotent.
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    install_log_redaction()


__all__ = ["JsonFormatter", "configure_logging"]
