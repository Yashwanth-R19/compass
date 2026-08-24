from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    # Deferred: app.engines.context imports app.engines.architecture and
    # app.engines.overlay (for its dependency-graph/hidden-dependency
    # accessors), both of which subclass Engine -- a top-level import here
    # would be circular. RunContext is only ever used as a type hint in this
    # module, so `from __future__ import annotations` plus a TYPE_CHECKING
    # guard is enough; nothing at runtime needs the real class.
    from app.engines.context import RunContext


class Engine(ABC):
    """Convention every analysis engine follows: pure over DB-loaded facts.

    ``run`` reads Facts by ``ctx.repo_id`` (repo_paths/commits/files/
    dependencies -- stable across a repo's whole history, see RepoPath's
    docstring in app/db/models.py) and prior Insight written earlier in the
    SAME run by ``ctx.run_id`` (coupling/file_metrics/findings/health --
    these tables hold rows from every past run of this repo too, so
    filtering by repo_id alone silently mixes runs together). It writes only
    Insight rows, every one of them tagged ``analysis_run_id=ctx.run_id``,
    back onto the same session. The caller owns the transaction -- an engine
    only executes inserts, it never deletes, commits, or rolls back -- so a
    full ingestion+analysis run stays one unit of work. A fresh run_id is
    empty by construction (Phase 02, CLAUDE.md), which is what makes
    "engines never delete" a structural guarantee rather than a convention.
    No engine ever touches git/network/filesystem. This is the technical
    embodiment of "analysis = pure functions over mined facts"
    (master-context.md sec 9, decision 1): same rows in, same rows out,
    every time, independent of git/network availability.

    ``ctx`` (session 01) is a per-run cache of derivations more than one
    engine needs (dependency graph, cycles, hidden dependencies, path maps)
    -- see app/engines/context.py. It is a caller-side convenience only: the
    independently-testable pure core of each engine still lives in a
    module-level ``compute_*`` function taking explicit ``repo_id``/
    ``run_id`` arguments, and the API layer calls those directly rather than
    building a context.
    """

    @abstractmethod
    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        """Compute this engine's results for ``ctx`` and persist them.

        Returns a small JSON-serializable metadata dict (counts, confidence
        flags, ...) -- also stored verbatim as the owning analysis_stages
        row's ``summary`` JSONB by app/jobs/stages.py's stage() context
        manager, and useful for job logging/tests. The metadata is never the
        source of truth -- the DB rows this writes are.
        """
        raise NotImplementedError
