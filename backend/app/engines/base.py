import uuid
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class Engine(ABC):
    """Convention every analysis engine follows: pure over DB-loaded facts.

    ``run`` reads only from the DB (no git, no filesystem, no network) and
    stages its computed results back onto the same session. The caller owns
    the transaction -- an engine only executes inserts/deletes, it never
    commits or rolls back -- so a full ingestion+analysis run stays one unit
    of work. This is the technical embodiment of "analysis = pure functions
    over mined facts" (master-context.md sec 9, decision 1): same rows in,
    same rows out, every time, independent of git/network availability.
    """

    @abstractmethod
    def run(self, repo_id: uuid.UUID, session: Session) -> dict[str, Any]:
        """Compute this engine's results for ``repo_id`` and persist them.

        Returns a small JSON-serializable metadata dict (counts, confidence
        flags, ...) useful for job logging/tests. The metadata is never the
        source of truth -- the DB rows this writes are.
        """
        raise NotImplementedError
