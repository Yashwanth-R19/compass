"""Historical evolution snapshots (session 13, Part B).

HONESTY CONSTRAINT (repeated here because it governs every metric this
module computes): every number in a snapshot is HISTORY-DERIVED -- recomputed
from the Facts layer using only commits with ``committed_at <= snapshot.date``.
Compass does NOT sample the import graph, subsystem partition, cyclomatic
complexity, or dependency cycles at historical points, because doing so would
require checking the tree out at that old revision (a `git checkout` dance
this session deliberately cuts -- see CLAUDE.md's "Timeline snapshots"
section for the full reasoning). The one place this shows up as a naming
choice rather than just a missing feature: the top-20-by-churn file ranking
is called ``churn_ranked_hotspots``, never "risk" -- risk is the LOCKED
formula (churn * complexity, plus coupling and commit-count terms), and
complexity at an old revision was never measured, so applying that formula
here would be a claim this session cannot back up.

Implemented as ONE pass over the repo's commits, accumulating running state
(cumulative churn, commit count, per-file churn, coupling changeset
counters, a trailing contributor-activity window) and emitting a snapshot's
worth of DERIVED metrics from that state the moment the pass reaches each
snapshot's commit index -- never 24 independent re-scans of the commit
history (Known Hazard #2). The coupling counters in particular are updated
once per commit and only ever READ (never rebuilt) at a snapshot boundary
(Known Hazard #3) -- rebuilding the pair-counting pass per snapshot would be
quadratic in changeset size, 24 times over.
"""

from __future__ import annotations

import itertools
import uuid
from collections import Counter, deque
from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.analysis.identities import most_frequent_recent, resolve_identities
from app.analysis.snapshots import HISTORY_SNAPSHOTS, select_snapshot_points
from app.db.models import Commit, File, Snapshot
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.coupling import MAX_CHANGESET_SIZE, MIN_COUPLING_DEGREE, MIN_SHARED_REVS

if TYPE_CHECKING:
    from app.engines.context import RunContext

ACTIVE_CONTRIBUTOR_WINDOW_DAYS = 90
"""Session 13, Part B: "active contributors in the preceding 90 days" -- a
plain, product-specified window, taken verbatim from the session prompt
rather than independently chosen (no HEURISTIC label -- it isn't this
engine's own invented number, it's a literal spec value, same category as
session 05's EXPERT_DOA_NORMALIZED_THRESHOLD being a cited constant rather
than a tuned one)."""

MAX_TOP_COUPLING_PAIRS = 10
"""Part B: "reporting only the pair count and the top 10 pairs -- not the
full matrix, for storage reasons"."""

MAX_CHURN_RANKED_HOTSPOTS = 20
"""Part B: "a risk-input ranking of the top 20 files"."""

MAX_TIMELINE_CONTRIBUTORS = 8
"""Judgement call (session 13, plan/RULES.md sec 2.5): Part B only specifies
a bare ``active_contributors`` COUNT, but Part F's "contributor band" needs a
per-person breakdown to render a stacked area distinguishing who is active
over time. Extends each snapshot with the top MAX_TIMELINE_CONTRIBUTORS
contributors (by commit count within the same trailing 90-day window used for
active_contributors) by DISPLAY NAME ONLY -- never an email, plan/RULES.md
sec 11.2 -- with the remainder folded into a single "Other" bucket so the
stacked area's bands always sum to 1.0 regardless of how many people were
actually active."""


class _CommitRow(NamedTuple):
    sha: str
    author_name: str
    author_email: str
    committed_at: Any
    changed_path_ids: tuple[int, ...]
    added_lines: tuple[int, ...]
    deleted_lines: tuple[int, ...]


def _load_commits(repo_id: uuid.UUID, session: Session) -> list[_CommitRow]:
    rows = session.execute(
        select(
            Commit.sha,
            Commit.author_name,
            Commit.author_email,
            Commit.committed_at,
            Commit.changed_path_ids,
            Commit.added_lines,
            Commit.deleted_lines,
        )
        .where(Commit.repo_id == repo_id)
        .order_by(Commit.committed_at.asc(), Commit.id.asc())
    ).all()
    return [
        _CommitRow(
            sha=r.sha,
            author_name=r.author_name,
            author_email=r.author_email,
            committed_at=r.committed_at,
            changed_path_ids=tuple(r.changed_path_ids),
            added_lines=tuple(r.added_lines),
            deleted_lines=tuple(r.deleted_lines),
        )
        for r in rows
    ]


def _canonical_names(
    commits: Sequence[_CommitRow], identity_map: dict[tuple[str, str], int]
) -> dict[int, str]:
    """One display name per resolved identity (session 05's
    ``most_frequent_recent`` -- most frequent value, tie-broken by most
    recent). Computed once over ALL commits, since the canonical name for a
    given identity is a property of the whole history, not of any one
    snapshot -- reused as a stable per-person label across every snapshot's
    ``contributor_shares`` band."""
    names_by_identity: dict[int, list[tuple[str, Any]]] = {}
    for c in commits:
        iid = identity_map[(c.author_name, c.author_email)]
        names_by_identity.setdefault(iid, []).append((c.author_name, c.committed_at))
    return {iid: most_frequent_recent(values) for iid, values in names_by_identity.items()}


def _load_file_lifetimes(repo_id: uuid.UUID, session: Session) -> list[tuple[Any, Any, bool]]:
    """``(first_seen, last_seen, is_deleted)`` for every file the miner ever
    saw for this repo -- the Facts-layer values ARE "first and last
    appearance in changesets" (app/ingestion/miner.py aggregates them as
    ``min``/``max`` of ``commit.committed_at`` over every commit touching that
    path), so this reuses them directly rather than re-deriving the same
    thing from a second walk over ``changed_path_ids``. See
    _file_count_alive_at for how "alive at snapshot T" is decided from these
    three fields."""
    rows = session.execute(
        select(File.first_seen, File.last_seen, File.is_deleted).where(File.repo_id == repo_id)
    ).all()
    return [(r.first_seen, r.last_seen, r.is_deleted) for r in rows]


def _file_count_alive_at(file_rows: Sequence[tuple[Any, Any, bool]], snapshot_date: Any) -> int:
    """A file counts as alive at ``snapshot_date`` when it had already been
    created (``first_seen <= snapshot_date``) AND either it survives to HEAD
    (``is_deleted`` False, so it can never have been removed) or its last
    touch -- which, for a file no longer in the current tree, is presumably
    the commit that removed it -- hasn't happened yet as of this snapshot
    (``last_seen > snapshot_date``). Judgement call (plan/RULES.md sec 2.5):
    the Facts layer has no per-commit add/delete status (git --numstat alone
    doesn't carry it), so "was this specific touch a deletion" is not
    directly knowable; treating a deleted file's own last recorded touch as
    its removal point is the same assumption a human skimming `git log`
    would make, and is exact for the overwhelmingly common case (a file's
    final touch in history IS the commit that deletes it)."""
    count = 0
    for first_seen, last_seen, is_deleted in file_rows:
        if first_seen > snapshot_date:
            continue
        if is_deleted and last_seen <= snapshot_date:
            continue
        count += 1
    return count


def _top_coupling_pairs(
    shared_revs: Counter[tuple[int, int]],
    file_revs: Counter[int],
    path_map: dict[int, str],
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Derives ``(pairs_count, top_pairs)`` from the CURRENT state of the
    running counters -- never rebuilds them. LOCKED FORMULA, verbatim,
    unchanged from app/engines/coupling.py: ``coupling_degree(A, B) =
    shared_revs / min(revs(A), revs(B))``, same MIN_SHARED_REVS/
    MIN_COUPLING_DEGREE thresholds, imported not redeclared."""
    rows: list[dict[str, Any]] = []
    for (path_a, path_b), shared in shared_revs.items():
        if shared < MIN_SHARED_REVS:
            continue
        revs_a, revs_b = file_revs[path_a], file_revs[path_b]
        coupling_degree = shared / min(revs_a, revs_b)
        if coupling_degree < MIN_COUPLING_DEGREE:
            continue
        rows.append(
            {
                "path_a": path_map.get(path_a, f"#{path_a}"),
                "path_b": path_map.get(path_b, f"#{path_b}"),
                "shared_revs": shared,
                "coupling_degree": coupling_degree,
            }
        )

    rows.sort(key=lambda r: (-r["coupling_degree"], -r["shared_revs"], r["path_a"], r["path_b"]))
    return len(rows), rows[:limit]


def _churn_ranked_hotspots(
    churn_by_path: Counter[int], path_map: dict[int, str], limit: int
) -> list[dict[str, Any]]:
    ranked = sorted(
        churn_by_path.items(),
        key=lambda kv: (-kv[1], path_map.get(kv[0], f"#{kv[0]}")),
    )[:limit]
    return [{"path": path_map.get(pid, f"#{pid}"), "churn_to_date": churn} for pid, churn in ranked]


def _contributor_shares(
    window: Sequence[tuple[Any, int]], name_by_identity: dict[int, str], limit: int
) -> list[dict[str, Any]]:
    """Top ``limit`` contributors by commit count within the CURRENT trailing
    90-day window (``window`` is a sequence of ``(committed_at, identity_id)``
    already trimmed to that window), by display name only -- never an email
    (plan/RULES.md sec 11.2). The remainder collapses into a single "Other"
    bucket so shares always sum to 1.0."""
    if not window:
        return []
    counts: Counter[int] = Counter(iid for _, iid in window)
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], name_by_identity.get(kv[0], "")))

    shares = [
        {"name": name_by_identity.get(iid, "Unknown"), "commits": n, "share": n / total}
        for iid, n in ranked[:limit]
    ]
    other_commits = sum(n for _, n in ranked[limit:])
    if other_commits:
        shares.append({"name": "Other", "commits": other_commits, "share": other_commits / total})
    return shares


def compute_timeline(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pure core: returns ``(snapshot_rows, stage_summary)``.

    ``snapshot_rows`` are plain dicts ready for a bulk insert into
    ``snapshots``, one per emitted SnapshotPoint, in chronological
    (``position`` 0-indexed) order. ``stage_summary`` is
    ``{"snapshots": n, "span_days": d}`` (Part B).

    Independently callable/testable, same "the compute_* function is the
    real source of truth, Engine.run is a caller-side convenience" pattern
    every other engine in this codebase follows (app/engines/base.py).
    """
    commits = _load_commits(repo_id, session)
    if not commits:
        return [], {"snapshots": 0, "span_days": 0}

    identity_map = resolve_identities([(c.author_name, c.author_email) for c in commits])
    name_by_identity = _canonical_names(commits, identity_map)

    points = select_snapshot_points([(c.sha, c.committed_at) for c in commits], HISTORY_SNAPSHOTS)
    boundary_at_index = {p.commit_index: p for p in points}

    path_map = load_path_map(repo_id, session)
    file_lifetimes = _load_file_lifetimes(repo_id, session)

    commits_to_date = 0
    churn_to_date = 0
    churn_by_path: Counter[int] = Counter()
    shared_revs: Counter[tuple[int, int]] = Counter()
    file_revs: Counter[int] = Counter()
    contributor_window: deque[tuple[Any, int]] = deque()

    snapshot_rows: list[dict[str, Any]] = []
    position = 0

    for i, c in enumerate(commits):
        commits_to_date += 1
        churn_to_date += sum(c.added_lines) + sum(c.deleted_lines)

        for pid, added, deleted in zip(
            c.changed_path_ids, c.added_lines, c.deleted_lines, strict=True
        ):
            churn_by_path[pid] += added + deleted

        unique_ids = sorted(set(c.changed_path_ids))
        if unique_ids and len(unique_ids) <= MAX_CHANGESET_SIZE:
            file_revs.update(unique_ids)
            shared_revs.update(itertools.combinations(unique_ids, 2))

        identity_id = identity_map[(c.author_name, c.author_email)]
        contributor_window.append((c.committed_at, identity_id))

        boundary = boundary_at_index.get(i)
        if boundary is None:
            continue

        cutoff = boundary.date - timedelta(days=ACTIVE_CONTRIBUTOR_WINDOW_DAYS)
        while contributor_window and contributor_window[0][0] < cutoff:
            contributor_window.popleft()

        active_ids = {iid for _, iid in contributor_window}
        pairs_count, top_pairs = _top_coupling_pairs(
            shared_revs, file_revs, path_map, MAX_TOP_COUPLING_PAIRS
        )

        metrics: dict[str, Any] = {
            "file_count": _file_count_alive_at(file_lifetimes, boundary.date),
            "churn_to_date": churn_to_date,
            "commits_to_date": commits_to_date,
            "active_contributors": len(active_ids),
            "contributor_shares": _contributor_shares(
                contributor_window, name_by_identity, MAX_TIMELINE_CONTRIBUTORS
            ),
            "coupling_pairs_count": pairs_count,
            "top_coupling_pairs": top_pairs,
            "churn_ranked_hotspots": _churn_ranked_hotspots(
                churn_by_path, path_map, MAX_CHURN_RANKED_HOTSPOTS
            ),
        }

        snapshot_rows.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "position": position,
                "commit_sha": boundary.sha,
                "at_date": boundary.date,
                "commit_index": boundary.commit_index,
                "metrics": metrics,
            }
        )
        position += 1

    span_days = (commits[-1].committed_at - commits[0].committed_at).days
    return snapshot_rows, {"snapshots": len(snapshot_rows), "span_days": span_days}


class TimelineEngine(Engine):
    """Historical evolution snapshots (session 13). Runs inside the existing
    "onboarding" stage, after GlossaryEngine and before HealthEngine (see
    app/jobs/stages.py) -- no new stage. Writes ``snapshots`` rows tagged
    ``analysis_run_id=ctx.run_id``; a fresh run_id has none of its own yet by
    construction, so this only inserts (app/engines/base.py's "engines never
    delete" rule)."""

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        rows, summary = compute_timeline(ctx.repo_id, ctx.run_id, session)
        if rows:
            session.execute(insert(Snapshot), rows)
        return summary
