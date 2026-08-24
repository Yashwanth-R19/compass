"""Shared "stale relative to repo activity" rule (session 05, Known Hazard
#1: ``datetime.now()`` is wrong here).

A contributor (or, from session 07 on, some other per-entity timestamp)
should never be judged stale against *today* -- that makes every archived
repository report its entire team as gone, which is a data-quality problem
disguised as a bug, not a real finding. The correct reference point is
always the REPOSITORY's own most recent commit: a repo whose last commit was
three years ago, with every contributor active within a month of each
other, has nobody stale at all, even though every one of them is "stale" by
the wall-clock.

Deliberately generic (no hardcoded threshold) so app/engines/expertise.py's
``STALE_AFTER_DAYS = 180`` and session 07's own threshold (whatever value it
turns out to need, for a different entity) both import this same comparison
rather than each reimplementing "days since, relative to repo activity."
"""

from datetime import datetime


def days_since_relative_to_repo_activity(
    timestamp: datetime, repo_last_commit_at: datetime
) -> float:
    """Days between ``timestamp`` and the repository's most recent commit --
    NOT ``datetime.now()``. Negative if ``timestamp`` is somehow after the
    repo's last commit (shouldn't happen for real data, but not guarded
    against here; the caller's threshold comparison handles it naturally
    since a negative value is always < any positive threshold)."""
    return (repo_last_commit_at - timestamp).total_seconds() / 86400


def is_stale_relative_to_repo(
    timestamp: datetime, repo_last_commit_at: datetime, threshold_days: int
) -> bool:
    """True when ``timestamp`` is more than ``threshold_days`` before the
    repository's own most recent commit. The threshold itself is the
    caller's choice (not fixed here) -- only the reference point (repo
    activity, never wall-clock) is shared."""
    return days_since_relative_to_repo_activity(timestamp, repo_last_commit_at) > threshold_days
