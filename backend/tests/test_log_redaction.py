import importlib
import logging

import pytest


@pytest.fixture
def redaction(monkeypatch):
    """Reload app.jobs.log_redaction with a controlled environment so the
    env-var-snapshot-at-import-time behaviour is deterministic per test.
    COMPASS_WORKER_SECRET's name matches the required marker set (TOKEN,
    SECRET, KEY, PASSWORD, DSN) -- COMPASS_WORKER_PAT deliberately would not
    (see the module docstring: PAT relies on the github_pat_ shape pattern
    instead, not name-based matching)."""
    monkeypatch.setenv("COMPASS_WORKER_SECRET", "super-secret-value-xyz")
    import app.jobs.log_redaction as module

    importlib.reload(module)
    yield module
    importlib.reload(module)  # restore normal env snapshot for later tests


def test_github_token_pattern_is_redacted(redaction):
    line = "cloning with token ghp_abcdefghijklmnopqrstuvwxyz1234 for auth"
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234" not in redaction.redact(line)
    assert "[REDACTED]" in redaction.redact(line)


def test_fine_grained_pat_pattern_is_redacted(redaction):
    line = "token=github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    result = redaction.redact(line)
    assert "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in result
    assert "[REDACTED]" in result


def test_postgres_url_is_redacted(redaction):
    line = "connecting to postgresql://user:hunter2@example.com:5432/db"
    result = redaction.redact(line)
    assert "hunter2" not in result
    assert "[REDACTED]" in result


def test_env_secret_value_is_redacted_as_literal_substring(redaction):
    line = "using worker secret super-secret-value-xyz to dispatch"
    result = redaction.redact(line)
    assert "super-secret-value-xyz" not in result
    assert "[REDACTED]" in result


def test_normal_line_survives_byte_identical(redaction):
    line = "stage 'coupling' completed: 214 pairs found, low_confidence=false"
    assert redaction.redact(line) == line


def test_filter_mutates_log_record_message(redaction):
    logger = logging.getLogger("test-redaction-logger")
    logger.setLevel(logging.INFO)
    logger.addFilter(redaction.RedactingFilter())

    records = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger.addHandler(_Capture())
    logger.info("token ghp_abcdefghijklmnopqrstuvwxyz1234 leaked")

    assert len(records) == 1
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234" not in records[0]
    assert "[REDACTED]" in records[0]
