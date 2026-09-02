"""Historical snapshot point selection (session 13, Part A).

``app/engines/timeline.py::TimelineEngine`` needs ``HISTORY_SNAPSHOTS`` points
spread across a repository's commit history to compute history-derived
metrics at. Picking those points is a pure, independently testable
computation, kept separate from the engine that consumes them -- same "the
pure compute_* core is the source of truth" discipline every other engine in
this codebase follows (app/engines/base.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

HISTORY_SNAPSHOTS = 24
"""How many points the evolution timeline samples across a repo's commit
history (session 13, Part A) -- fixed, not configurable per repo. A repo with
fewer commits than this gets one snapshot per commit instead (see
select_snapshot_points), and the actual count is reported honestly rather
than padded to 24."""


@dataclass(frozen=True)
class SnapshotPoint:
    sha: str
    date: datetime
    commit_index: int
    """0-based position of this commit within the chronologically sorted
    commit list -- what app/engines/timeline.py's single accumulation pass
    matches against to know when to emit a snapshot."""


def select_snapshot_points(
    commits: Sequence[tuple[str, datetime]], n: int = HISTORY_SNAPSHOTS
) -> list[SnapshotPoint]:
    """Chooses up to ``n`` points evenly spaced by COMMIT INDEX, not by date.

    Repositories routinely have long dormant stretches (idle for eight
    months, then a burst of activity). Spacing snapshots evenly by DATE would
    waste most of them sampling nothing happening during the dormant period
    and crowd none of them into the burst where the interesting change
    actually occurred. Spacing by commit index instead guarantees every
    snapshot represents roughly the same amount of actual development
    activity, regardless of how unevenly it's distributed over wall-clock
    time -- this is the reasoning the session prompt explicitly asks to be
    recorded here.

    ``commits`` is a sequence of ``(sha, committed_at)`` pairs, any order --
    sorted chronologically here (ties broken by sha for determinism, the same
    "an unordered input must never leak into nondeterministic output" rule
    every other engine in this codebase follows, e.g.
    app/analysis/identities.py's union-find). Always includes the first and
    last commit. Deterministic for a given commit list, independent of the
    input's original order.

    When there are fewer commits than ``n``, returns one snapshot per commit
    -- the caller reports the actual, smaller count (see TimelineEngine's
    stage summary), never padded up to look like a full 24.
    """
    if not commits:
        return []

    ordered = sorted(commits, key=lambda c: (c[1], c[0]))
    total = len(ordered)

    if total <= n:
        return [
            SnapshotPoint(sha=sha, date=date, commit_index=i)
            for i, (sha, date) in enumerate(ordered)
        ]

    if n <= 1:
        indices = [total - 1]
    else:
        # Evenly spaced by commit index: i=0 always lands on 0, i=n-1 always
        # lands on total-1. Rounding can occasionally collide two adjacent
        # i's onto the same index for a small total/n ratio -- dedupe via a
        # sorted set rather than assuming exactly n distinct indices come out
        # (the "fewer commits than n" branch above already handles the case
        # where total <= n, so a collision here just means a slightly-under-n
        # result, which is fine and still deterministic).
        indices = sorted({round(i * (total - 1) / (n - 1)) for i in range(n)})

    return [SnapshotPoint(sha=ordered[i][0], date=ordered[i][1], commit_index=i) for i in indices]
