"""Blast radius (session 07, Part A): "if I change this file, what else is
affected, and how confident should I be?" -- answered from two independent
angles that are deliberately kept apart rather than blended into one score:

- STRUCTURAL: files that transitively IMPORT the target, walked backward
  through the dependency graph (Facts, repo_id-scoped, unaffected by which
  run is selected -- same as /architecture).
- HISTORICAL: files that CO-CHANGE with the target at a real coupling_degree
  (Insight, this run's persisted `coupling` rows).

The interesting set is files in the historical set but NOT the structural
one -- high co-change with no import path at any depth this computation
explored. That asymmetry (coupled but not imported) is the whole reason this
feature exists; see BlastRadius.surprising_affected below.

This is a PURE FUNCTION MODULE, not an Engine (app/engines/base.py) --
called on demand from the API, computes nothing ahead of time, and persists
NOTHING (Known Hazard #8: there are thousands of files, and a blast radius
is per-(file, depth), not a fixed per-run quantity the way coupling/risk
are). The only state this module keeps between calls is the small
per-run dependency-graph cache below, and that cache holds a `networkx`
graph only -- never a row, a session, or anything SQLAlchemy-bound (Known
Hazard #7).
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass

import networkx as nx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Commit,
    Contributor,
    Coupling,
    File,
    FileExpertise,
    FileMetrics,
    Subsystem,
    SubsystemMember,
)
from app.db.paths import load_path_id_map, load_path_map
from app.engines.architecture import build_graph, load_edges

MAX_BLAST_DEPTH = 6
DEFAULT_BLAST_DEPTH = 3
MAX_BLAST_NODES = 500
"""Anti-runaway caps on the structural BFS (Part A step 2): a repo with a
dense import graph could otherwise walk arbitrarily far/wide from one file.
Both are reported to the caller when they engage -- silently truncating
would misrepresent "this is the whole blast radius" as fact."""

MIN_HISTORICAL_COUPLING_DEGREE = 0.30
"""Reuses CouplingEngine's own MIN_COUPLING_DEGREE floor (app/engines/coupling.py)
-- a `coupling` row can never exist below this anyway, so this constant is
here for readability at the call site, not because a stricter filter is
being applied on top of what CouplingEngine already persisted."""

MAX_EVIDENCE_FILES = 5
MAX_EXAMPLE_SHAS = 3
"""Part A step 6: how many of the top (by coupling_degree) historically
affected files get commit-level evidence, and how many example shas each
gets -- anti-alert-fatigue caps, same discipline as every other list in this
codebase."""

BLAST_GRAPH_CACHE_SIZE = 8
"""Small per-process LRU of built dependency graphs, keyed by analysis
run_id. Rebuilding a several-thousand-edge graph on every blast-radius
request is wasteful when the same run is being explored interactively (a
user clicking through several files' blast radii in one repo view); holding
8 is a few megabytes even for a large repo.

Invalidation story: entries are keyed by an IMMUTABLE run_id, so a cached
entry can never go stale FOR THAT RUN -- `dependencies` (Facts) only
changes when a NEW ingestion run replaces it (app/db/wipe.py::wipe_facts),
and a new run always gets a fresh run_id (Facts/Insight split, CLAUDE.md).
This is the same non-staleness property /architecture's per-request
RunContext relies on, just cached across requests instead of within one.
Like app/api/limits.py's token-bucket limiter, this cache is correct for
exactly one process -- if Compass is ever deployed across more than one API
instance, each instance simply keeps its own independent cache (a stale
read is impossible either way, so this is a pure performance concern, not
a correctness one)."""

_graph_cache: OrderedDict[uuid.UUID, nx.DiGraph] = OrderedDict()
_graph_cache_lock = threading.Lock()


def _cached_dependency_graph(repo_id: uuid.UUID, run_id: uuid.UUID, session: Session) -> nx.DiGraph:
    """Cache the `networkx` graph only -- never rows or a session (Known
    Hazard #7). `load_edges` is called at most once per (repo_id, run_id)
    pair per process, until evicted by the LRU."""
    with _graph_cache_lock:
        cached = _graph_cache.get(run_id)
        if cached is not None:
            _graph_cache.move_to_end(run_id)
            return cached

    edges = load_edges(repo_id, session)
    graph = build_graph(edges)

    with _graph_cache_lock:
        _graph_cache[run_id] = graph
        _graph_cache.move_to_end(run_id)
        while len(_graph_cache) > BLAST_GRAPH_CACHE_SIZE:
            _graph_cache.popitem(last=False)

    return graph


@dataclass
class AffectedFile:
    path: str
    hop_distance: int | None  # None when this file is only in the historical set
    coupling_degree: float | None  # None when this file is only in the structural set
    risk_score: float | None


@dataclass
class HistoricalEvidence:
    affected_path: str
    shared_commit_count: int
    shared_commit_percentage: float
    example_shas: list[str]


@dataclass
class ExpertToReview:
    contributor_id: int
    canonical_name: str


@dataclass
class BlastRadius:
    path: str
    depth: int
    depth_capped: bool
    node_cap_engaged: bool
    structural_affected: list[AffectedFile]
    historical_affected: list[AffectedFile]
    surprising_affected: list[AffectedFile]
    total_affected_count: int
    percentage_of_repo_files: float
    subsystems_touched: list[str]
    experts_to_review: list[ExpertToReview]
    total_affected_risk_score: float
    commits_touching_path: int
    historical_evidence: list[HistoricalEvidence]


def _structural_blast_radius(
    graph: nx.DiGraph, path: str, max_depth: int, max_nodes: int
) -> tuple[dict[str, int], bool, bool]:
    """BFS over `path`'s PREDECESSORS -- a structural edge (A, B) means "A
    imports B" (app/engines/architecture.py::load_edges), so "what
    transitively imports path" is a reverse-traversal from it, not a
    forward one. Returns (hop_distance_by_path, depth_capped,
    node_cap_engaged). Deterministic: predecessors are expanded in sorted
    order at each BFS layer.
    """
    if path not in graph:
        return {}, False, False

    hop_distance: dict[str, int] = {}
    seen = {path}
    queue: deque[tuple[str, int]] = deque([(path, 0)])
    depth_capped = False
    node_cap_engaged = False

    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            if any(pred not in seen for pred in graph.predecessors(node)):
                depth_capped = True
            continue
        for pred in sorted(graph.predecessors(node)):
            if pred in seen:
                continue
            if len(hop_distance) >= max_nodes:
                node_cap_engaged = True
                continue
            seen.add(pred)
            hop_distance[pred] = depth + 1
            queue.append((pred, depth + 1))

    return hop_distance, depth_capped, node_cap_engaged


def _historical_blast_radius(
    repo_id: uuid.UUID, run_id: uuid.UUID, path_id: int, session: Session
) -> dict[int, float]:
    """path_id -> coupling_degree for every file coupled with `path_id` at
    >= MIN_HISTORICAL_COUPLING_DEGREE for this run (Part A step 3) -- reads
    the already-persisted `coupling` rows, never recomputes them."""
    rows = session.execute(
        select(Coupling.path_a_id, Coupling.path_b_id, Coupling.coupling_degree).where(
            Coupling.repo_id == repo_id,
            Coupling.analysis_run_id == run_id,
            (Coupling.path_a_id == path_id) | (Coupling.path_b_id == path_id),
        )
    ).all()
    degree_by_path_id: dict[int, float] = {}
    for a_id, b_id, degree in rows:
        other = b_id if a_id == path_id else a_id
        degree_by_path_id[other] = max(degree_by_path_id.get(other, 0.0), degree)
    return degree_by_path_id


def compute_blast_radius(
    session: Session,
    run_id: uuid.UUID,
    repo_id: uuid.UUID,
    path: str,
    max_depth: int = DEFAULT_BLAST_DEPTH,
    max_nodes: int = MAX_BLAST_NODES,
) -> BlastRadius:
    """Pure computation, no writes (Known Hazard #8). `max_nodes` is
    exposed as a parameter (not just the module constant) purely so tests
    can exercise the node cap without constructing a 500+ node fixture --
    the API layer never overrides it."""
    max_depth = min(max(max_depth, 1), MAX_BLAST_DEPTH)

    path_id_map = load_path_id_map(repo_id, session)
    path_id = path_id_map[path]

    graph = _cached_dependency_graph(repo_id, run_id, session)
    hop_by_path, depth_capped, node_cap_engaged = _structural_blast_radius(
        graph, path, max_depth, max_nodes
    )
    structural_paths = set(hop_by_path)

    degree_by_path_id = _historical_blast_radius(repo_id, run_id, path_id, session)
    path_map = load_path_map(repo_id, session)
    degree_by_path = {
        path_map[pid]: degree for pid, degree in degree_by_path_id.items() if pid in path_map
    }
    historical_paths = set(degree_by_path)

    surprising_paths = historical_paths - structural_paths

    affected_paths = structural_paths | historical_paths

    risk_by_path: dict[str, float] = {}
    if affected_paths:
        affected_path_ids = {path_id_map[p] for p in affected_paths if p in path_id_map}
        risk_rows = session.execute(
            select(FileMetrics.path_id, FileMetrics.risk_score).where(
                FileMetrics.analysis_run_id == run_id,
                FileMetrics.path_id.in_(affected_path_ids),
            )
        ).all()
        risk_by_path = {
            path_map[pid]: (score or 0.0) for pid, score in risk_rows if pid in path_map
        }

    def _to_affected_file(p: str) -> AffectedFile:
        return AffectedFile(
            path=p,
            hop_distance=hop_by_path.get(p),
            coupling_degree=degree_by_path.get(p),
            risk_score=risk_by_path.get(p),
        )

    structural_affected = sorted(
        (_to_affected_file(p) for p in structural_paths), key=lambda a: (a.hop_distance, a.path)
    )
    historical_affected = sorted(
        (_to_affected_file(p) for p in historical_paths),
        key=lambda a: (-(a.coupling_degree or 0.0), a.path),
    )
    # The money output (module docstring): surprises sorted first by
    # coupling_degree desc, same ranking discipline as every other
    # anti-alert-fatigue list in this codebase (master-context.md sec 7).
    surprising_affected = sorted(
        (_to_affected_file(p) for p in surprising_paths),
        key=lambda a: (-(a.coupling_degree or 0.0), a.path),
    )

    repo_file_count = (
        session.scalar(
            select(func.count())
            .select_from(File)
            .where(File.repo_id == repo_id, File.is_deleted.is_(False))
        )
        or 0
    )
    percentage_of_repo_files = len(affected_paths) / repo_file_count if repo_file_count else 0.0

    subsystems_touched: list[str] = []
    if affected_paths:
        affected_path_ids = {path_id_map[p] for p in affected_paths if p in path_id_map}
        subsystem_rows = session.execute(
            select(Subsystem.label)
            .join(SubsystemMember, SubsystemMember.subsystem_id == Subsystem.id)
            .where(
                Subsystem.analysis_run_id == run_id,
                SubsystemMember.path_id.in_(affected_path_ids),
            )
            .distinct()
        ).all()
        subsystems_touched = sorted(label for (label,) in subsystem_rows)

    experts_to_review: list[ExpertToReview] = []
    if affected_paths:
        affected_path_ids = {path_id_map[p] for p in affected_paths if p in path_id_map}
        expert_rows = session.execute(
            select(Contributor.id, Contributor.canonical_name)
            .join(FileExpertise, FileExpertise.contributor_id == Contributor.id)
            .where(
                FileExpertise.analysis_run_id == run_id,
                FileExpertise.path_id.in_(affected_path_ids),
                FileExpertise.is_expert.is_(True),
            )
            .distinct()
        ).all()
        experts_to_review = sorted(
            (ExpertToReview(contributor_id=cid, canonical_name=name) for cid, name in expert_rows),
            key=lambda e: e.canonical_name,
        )

    total_affected_risk_score = sum(risk_by_path.get(p, 0.0) for p in affected_paths)

    commits_touching_path, historical_evidence = _historical_evidence(
        repo_id, path_id, historical_affected, path_id_map, session
    )

    return BlastRadius(
        path=path,
        depth=max_depth,
        depth_capped=depth_capped,
        node_cap_engaged=node_cap_engaged,
        structural_affected=structural_affected,
        historical_affected=historical_affected,
        surprising_affected=surprising_affected,
        total_affected_count=len(affected_paths),
        percentage_of_repo_files=percentage_of_repo_files,
        subsystems_touched=subsystems_touched,
        experts_to_review=experts_to_review,
        total_affected_risk_score=total_affected_risk_score,
        commits_touching_path=commits_touching_path,
        historical_evidence=historical_evidence,
    )


def _historical_evidence(
    repo_id: uuid.UUID,
    path_id: int,
    historical_affected: list[AffectedFile],
    path_id_map: dict[str, int],
    session: Session,
) -> tuple[int, list[HistoricalEvidence]]:
    """Part A step 6: turns the historical-blast-radius claim into evidence
    -- for the top MAX_EVIDENCE_FILES affected files (already ranked by
    coupling_degree desc), how many (and what percentage) of the commits
    that touched `path` also touched that file, plus up to
    MAX_EXAMPLE_SHAS example commit shas."""
    commits = session.execute(
        select(Commit.sha, Commit.changed_path_ids).where(
            Commit.repo_id == repo_id, Commit.changed_path_ids.any(path_id)  # type: ignore[arg-type]
        )
    ).all()
    total = len(commits)
    if total == 0 or not historical_affected:
        return total, []

    evidence: list[HistoricalEvidence] = []
    for affected in historical_affected[:MAX_EVIDENCE_FILES]:
        affected_path_id = path_id_map.get(affected.path)
        if affected_path_id is None:
            continue
        shared = [sha for sha, changed in commits if affected_path_id in set(changed)]
        evidence.append(
            HistoricalEvidence(
                affected_path=affected.path,
                shared_commit_count=len(shared),
                shared_commit_percentage=len(shared) / total,
                example_shas=shared[:MAX_EXAMPLE_SHAS],
            )
        )
    return total, evidence
