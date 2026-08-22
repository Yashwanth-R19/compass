import logging
import os
import re

REDACTED = "[REDACTED]"

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"postgres(ql)?://[^\s]+"),
    # Session 02, Part D: the private-repo clone URL
    # (app/ingestion/clone_url.py::resolve_clone_url) embeds a live GitHub
    # token as the URL's userinfo -- `https://x-access-token:<token>@...`.
    # The token itself already matches the gh[pousr]_ pattern above in
    # practice, but this pattern catches the whole credential regardless of
    # the token's shape, since a failed git clone's own error text
    # (git.exc.GitCommandError, app/ingestion/cloner.py) echoes this exact
    # URL back verbatim.
    re.compile(r"x-access-token:[^@\s]+@"),
]
"""Patterns scrubbed from every log line regardless of source -- GitHub
tokens (classic and fine-grained), any Postgres connection string, and the
x-access-token clone-URL credential. This list is deliberately conservative
in the other direction from usual: it is fine, even expected, for
`postgres://...` to eat a whole legitimate-looking URL in a log line -- the
alternative (a partial match that leaves a password fragment visible) is the
failure that matters here (session 01, CLAUDE.md's public-logs constraint).
See test_log_redaction.py for the "a normal line survives byte-identical"
regression guard that catches an over-eager pattern in the other direction.
"""


def _env_secret_values() -> list[str]:
    """Snapshot, at import time, the value of every environment variable
    whose NAME contains TOKEN, SECRET, KEY, PASSWORD, or DSN -- these are
    scrubbed as literal substrings wherever they appear in a log line, in
    addition to the regex patterns above (which only catch known secret
    *shapes*; this catches anything else marked secret by its env var name,
    e.g. COMPASS_WORKER_PAT would not match any pattern above by shape
    alone, but its value is still a live credential).
    """
    markers = ("TOKEN", "SECRET", "KEY", "PASSWORD", "DSN")
    values = []
    for name, value in os.environ.items():
        if not value:
            continue
        if any(marker in name.upper() for marker in markers):
            values.append(value)
    # Longest first: a shorter secret value that happens to be a substring
    # of a longer one must not partially redact the longer one first.
    values.sort(key=len, reverse=True)
    return values


_ENV_SECRET_VALUES = _env_secret_values()


def redact(message: str) -> str:
    """Replace every known secret pattern/value in ``message`` with
    ``[REDACTED]``. A message containing none of them is returned
    byte-identical -- see test_log_redaction.py's normal-line test, which
    exists specifically to catch an over-eager pattern that mangles ordinary
    output.
    """
    for value in _ENV_SECRET_VALUES:
        if value in message:
            message = message.replace(value, REDACTED)
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(REDACTED, message)
    return message


class RedactingFilter(logging.Filter):
    """A logging.Filter, not a Formatter -- filters run before a record's
    args are merged into its message and before any Formatter renders it,
    and mutating ``record.msg``/``record.args`` here means every handler
    downstream (including ones added later) sees the redacted text, not just
    whichever handler happens to have this Formatter attached.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def install_log_redaction() -> None:
    """Installs ``RedactingFilter`` on the root logger. Must run before
    anything else in worker.py -- the GitHub Actions workflow repository is
    public, so its logs are public; every line any code prints via the
    ``logging`` module after this call is scrubbed before it reaches
    stdout/stderr. Does not affect bare ``print()`` calls, which is why
    worker.py's own error handling logs through ``logging`` rather than
    printing exception text directly (see its module docstring).
    """
    root = logging.getLogger()
    for existing in root.filters:
        if isinstance(existing, RedactingFilter):
            return
    root.addFilter(RedactingFilter())
