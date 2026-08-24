import uuid
from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy.orm import Session

from app.db.paths import load_path_id_map, load_path_map
from app.engines.architecture import build_graph, find_cycles, load_edges
from app.engines.overlay import HiddenDependency, compute_hidden_dependencies


@dataclass
class RunContext:
    """Per-run cache of derived artifacts more than one engine reads.

    Rules (session 01, CLAUDE.md "The run context"):

    - It is a cache, never a source of truth. Every accessor is a pure
      function of rows already in the database at the time it is first
      called -- calling it twice in the same process, before or after, must
      never change what it returns.
    - It is scoped to exactly one ``(repo_id, run_id)`` and must never be
      reused across runs or shared between requests. Construct one per
      ingestion job and one per API request that needs it.
    - It must never be mutated by an engine to pass side-channel data to a
      later engine. If engine B needs engine A's output, B reads A's
      persisted rows. The context exists to avoid recomputation of
      derivations from the database, not to avoid persistence.
    - Memoisation is per-instance, plain instance attributes -- deliberately
      not ``functools.lru_cache``, which would key on the ``session``
      argument and silently leak cached results across sessions/runs if a
      method were ever called twice with different sessions.
    """

    repo_id: uuid.UUID
    run_id: uuid.UUID

    _dependency_edges: list[tuple[str, str]] | None = field(default=None, init=False, repr=False)
    _dependency_graph: nx.DiGraph | None = field(default=None, init=False, repr=False)
    _cycles: list[list[str]] | None = field(default=None, init=False, repr=False)
    _hidden_dependencies: list[HiddenDependency] | None = field(
        default=None, init=False, repr=False
    )
    _path_map: dict[int, str] | None = field(default=None, init=False, repr=False)
    _path_id_map: dict[str, int] | None = field(default=None, init=False, repr=False)

    def dependency_edges(self, session: Session) -> list[tuple[str, str]]:
        if self._dependency_edges is None:
            self._dependency_edges = load_edges(self.repo_id, session)
        return self._dependency_edges

    def dependency_graph(self, session: Session) -> nx.DiGraph:
        if self._dependency_graph is None:
            self._dependency_graph = build_graph(self.dependency_edges(session))
        return self._dependency_graph

    def cycles(self, session: Session) -> list[list[str]]:
        if self._cycles is None:
            self._cycles = find_cycles(self.dependency_graph(session))
        return self._cycles

    def hidden_dependencies(self, session: Session) -> list[HiddenDependency]:
        if self._hidden_dependencies is None:
            self._hidden_dependencies = compute_hidden_dependencies(
                self.repo_id, self.run_id, session
            )
        return self._hidden_dependencies

    def path_map(self, session: Session) -> dict[int, str]:
        if self._path_map is None:
            self._path_map = load_path_map(self.repo_id, session)
        return self._path_map

    def path_id_map(self, session: Session) -> dict[str, int]:
        if self._path_id_map is None:
            self._path_id_map = load_path_id_map(self.repo_id, session)
        return self._path_id_map
