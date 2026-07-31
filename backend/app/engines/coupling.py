import itertools
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import Commit, Coupling
from app.engines.base import Engine

# ---- Config (module-level, documented; not per-caller knobs) ----

MAX_CHANGESET_SIZE = 30
"""Commits touching more files than this are dropped before coupling is
computed at all. Merges, mass reformats, and repo-wide renames touch dozens
of unrelated files in one commit and would manufacture spurious coupling
between files that never actually change together for a real reason
(master-context.md sec 5, step 2)."""

MIN_SHARED_REVS = 5
"""Minimum number of commits two files must share to be considered coupled.
A code-maat default: below this, a shared revision or two is noise, not a
recurring pattern."""

MIN_COUPLING_DEGREE = 0.30
"""Minimum coupling_degree (see formula below) required to keep a pair.
Also a code-maat default."""

FALLBACK_MIN_SHARED_REVS = 2
"""Lowered shared_revs floor used ONLY when the normal MIN_SHARED_REVS floor
produces zero pairs for the whole repo -- i.e. every real pair's shared_revs
falls below it. That's a property of the actual commit history (do any two
files ever repeatedly co-change?), not just "this repo has few commits" --
a 15-commit repo can easily have a pair sharing 5+ of them, while a
4-commit repo obviously can't reach 5 no matter what. Returning an honestly
low-confidence answer computed at this lower floor is more useful than
silently returning an empty list on a small repo (master-context.md sec
6/13). MIN_COUPLING_DEGREE is NOT lowered alongside this -- it's a ratio,
not a count, so it stays meaningful regardless of history depth."""


def load_kept_changesets(repo_id: uuid.UUID, session: Session) -> list[list[int]]:
    """Per-commit changesets (as sorted, deduped lists of repo_paths.id) for
    ``repo_id``, with mega-commits (> MAX_CHANGESET_SIZE distinct files) and
    empty changesets already dropped.

    Reads ``commits.changed_path_ids`` directly -- no commit_files join
    (Phase 1 schema diet). Exposed (not engine-private) so the coupling
    API/OverlayEngine can independently derive the same "how much history
    did we actually analyze" signal used for the low-confidence flag,
    without duplicating the query/threshold.
    """
    rows = session.scalars(select(Commit.changed_path_ids).where(Commit.repo_id == repo_id)).all()

    changesets: list[list[int]] = []
    for path_ids in rows:
        unique_ids = sorted(set(path_ids))
        if not unique_ids:
            continue
        if len(unique_ids) <= MAX_CHANGESET_SIZE:
            changesets.append(unique_ids)
    return changesets


def _pair_stats(changesets: list[list[int]]) -> tuple[Counter[tuple[int, int]], Counter[int]]:
    shared_revs: Counter[tuple[int, int]] = Counter()
    file_revs: Counter[int] = Counter()
    for path_ids in changesets:
        file_revs.update(path_ids)
        # path_ids is already sorted, so combinations() always produces the
        # same (lower_id, higher_id) key for a given pair regardless of
        # which commit it came from -- what makes shared_revs accumulate
        # correctly across commits.
        shared_revs.update(itertools.combinations(path_ids, 2))
    return shared_revs, file_revs


def _build_rows(
    repo_id: uuid.UUID,
    shared_revs: Counter[tuple[int, int]],
    file_revs: Counter[int],
    min_shared_revs: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (path_a, path_b), shared in shared_revs.items():
        if shared < min_shared_revs:
            continue

        revs_a, revs_b = file_revs[path_a], file_revs[path_b]

        # LOCKED FORMULA -- coupling_degree(A, B) = shared_revs / min(revs(A), revs(B))
        # This exact formula is used nowhere else and must never drift to a
        # different variant (max/avg/A-only). Dividing by the LESS-active
        # file is deliberate: it's what surfaces a rarely-touched file that
        # almost always changes alongside a much busier one (e.g. B has 6
        # commits total and all 6 also touch A) -- that's a strong
        # hidden-dependency signal precisely because B can barely change
        # without A. Dividing by the more-active file (or by A alone) would
        # crush that ratio and hide exactly the pattern this feature exists
        # to catch (master-context.md sec 5).
        coupling_degree = shared / min(revs_a, revs_b)

        if coupling_degree < MIN_COUPLING_DEGREE:
            continue

        # avg_revs: secondary, non-diluting activity signal -- stored and
        # returned for context only, never used in thresholding.
        avg_revs = (revs_a + revs_b) / 2

        rows.append(
            {
                "repo_id": repo_id,
                "path_a_id": path_a,
                "path_b_id": path_b,
                "shared_revs": shared,
                "coupling_degree": coupling_degree,
                "avg_revs": avg_revs,
            }
        )
    return rows


def compute_coupling(
    repo_id: uuid.UUID, session: Session
) -> tuple[list[dict[str, Any]], bool, int]:
    """Returns ``(rows, low_confidence, commits_analyzed)``.

    Tries the normal MIN_SHARED_REVS floor first. If that yields nothing at
    all -- but the repo does have some analyzed history -- retries with the
    lowered FALLBACK_MIN_SHARED_REVS floor and marks the whole result set
    low-confidence (see FALLBACK_MIN_SHARED_REVS above for why the trigger
    is "did the normal floor actually produce zero pairs", not a raw commit
    count cutoff). Single source of truth for CouplingEngine (persists these
    rows) and for is_low_confidence()/the coupling API (read the flag
    without re-deciding the threshold logic separately).

    Reads only Facts (``commits.changed_path_ids``) -- no ``run_id``
    parameter needed, unlike most other engines' compute_* helpers, because
    this one never reads the run-scoped ``coupling`` table itself, only
    writes to it (CouplingEngine tags ``analysis_run_id`` onto these rows
    before inserting).
    """
    changesets = load_kept_changesets(repo_id, session)
    if not changesets:
        return [], False, 0

    shared_revs, file_revs = _pair_stats(changesets)

    rows = _build_rows(repo_id, shared_revs, file_revs, MIN_SHARED_REVS)
    if rows:
        return rows, False, len(changesets)

    fallback_rows = _build_rows(repo_id, shared_revs, file_revs, FALLBACK_MIN_SHARED_REVS)
    return fallback_rows, True, len(changesets)


def is_low_confidence(repo_id: uuid.UUID, session: Session) -> bool:
    """True when CouplingEngine had to fall back to the lowered shared_revs
    floor for this repo (see compute_coupling)."""
    _, low_confidence, _ = compute_coupling(repo_id, session)
    return low_confidence


def confidence_hint(shared_revs: int, low_confidence_repo: bool) -> str:
    """Heuristic confidence label surfaced in the API and in hidden-dependency
    findings -- not a stored column (the Coupling row already carries
    shared_revs/avg_revs as the underlying evidence a reader can judge
    themselves). Always "low" when the repo-wide small-repo fallback applies;
    otherwise scaled off shared_revs relative to the normal floor.
    """
    if low_confidence_repo:
        return "low"
    if shared_revs >= MIN_SHARED_REVS * 2:
        return "high"
    return "medium"


CONFIDENCE_SCORE = {"low": 0.4, "medium": 0.65, "high": 0.9}
"""Numeric form of confidence_hint()'s labels, for callers (the overlay
engine's hidden-dependency findings) that need a float rather than a
string."""


class CouplingEngine(Engine):
    """Mines logical/change coupling from persisted commit history.

    Reads only ``commits.changed_path_ids`` for ``repo_id`` -- no join, no
    git, no network (master-context.md sec 5, the flagship feature; Phase 1
    schema diet removed the commit_files join table). Writes rows tagged
    ``analysis_run_id=run_id``; a fresh run_id has no coupling rows of its
    own yet by construction (Facts/Insight split, Phase 02), so this engine
    only inserts, it never deletes-first.
    """

    def run(self, repo_id: uuid.UUID, run_id: uuid.UUID, session: Session) -> dict[str, Any]:
        rows, low_confidence, commits_analyzed = compute_coupling(repo_id, session)

        if rows:
            tagged_rows = [{"analysis_run_id": run_id, **row} for row in rows]
            session.execute(insert(Coupling), tagged_rows)

        return {
            "pairs_found": len(rows),
            "commits_analyzed": commits_analyzed,
            "low_confidence": low_confidence,
        }
