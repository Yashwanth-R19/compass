from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import networkx as nx
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.analysis.stopwords import STOPWORDS, tokenize_identifier
from app.db.models import (
    Coupling,
    Dependency,
    File,
    Finding,
    Severity,
    Subsystem,
    SubsystemMember,
    Symbol,
)
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.signature import finding_signature

if TYPE_CHECKING:
    from app.engines.context import RunContext

# ---- Config (module-level, documented; not per-caller knobs) ----

W_STRUCT = 1.0
"""HEURISTIC (plan/RULES.md sec 3): edge weight contributed by a single
structural (import) edge between two files in the combined subsystem graph."""

W_COUPLE = 1.5
"""HEURISTIC (plan/RULES.md sec 3): edge weight contributed by a coupling
pair is ``W_COUPLE * coupling_degree`` -- coupling is weighted slightly
HIGHER than a single import because a strong co-change relationship (the
files are repeatedly edited together across real history) is stronger
evidence that two files "belong together" than one static import statement
is -- an import can be a thin, stable interface; a persistent co-change
pattern means the two files are functionally inseparable in practice
(master-context.md sec 5's whole argument for why coupling matters at all).
The LOCKED coupling_degree formula itself (app/engines/coupling.py) is never
touched here -- this only scales its already-computed value as one input to
an unrelated, heuristic clustering weight."""

LOUVAIN_SEED = 42
"""Determinism is a core product claim (master-context.md sec 2/plan/RULES.md
sec 4): the same repo at the same head_sha must produce the identical
subsystem partition every run. Louvain's local-move phase is randomized
internally; without a fixed seed, two runs over the IDENTICAL graph can land
on different (locally-optimal) partitions. Seeding alone is not enough by
itself either -- see the module-level sort applied to the resulting
community list below, which removes the OTHER source of nondeterminism
(iterating a Python set/dict of communities in an order that isn't itself
fixed by anything other than object hashes)."""

LOUVAIN_RESOLUTION = 1.0
"""HEURISTIC: Louvain's resolution parameter -- higher values favor more,
smaller communities; lower values favor fewer, larger ones. 1.0 is
networkx's own default (no repo-specific tuning)."""

MIN_SUBSYSTEM_SIZE = 3
"""HEURISTIC: a 1- or 2-file "community" isn't a subsystem a person can
reason about -- it reads as clustering noise. Merged into its
strongest-connected neighbour (see ``_merge_small_communities``), or into
the "Unclustered" catch-all when it has no edges to merge toward at all."""

MAX_SUBSYSTEMS = 12
"""HEURISTIC: a person cannot hold 30 subsystems in their head at once, and
comprehension is the entire point of this feature (session 04 spec). Beyond
this, the smallest excess communities are folded into a single "Other"
bucket rather than reported individually."""

_GENERIC_DIR_SEGMENTS = frozenset({"src", "lib", "impl", "internal", "pkg"})
"""Directory segments too generic to stand alone as a subsystem label (e.g.
nearly every repo has a top-level ``src/``) -- when the deepest qualifying
path-prefix segment is one of these AND a second segment is available, the
label falls back to "<parent>/<segment>" instead (see ``_path_prefix_label``).
Deliberately a SEPARATE, smaller list from ``app.analysis.stopwords.STOPWORDS``
-- these are directory-naming conventions, not identifier noise, and mixing
the two lists would make STOPWORDS's own semantics (session 06 reuses it for
glossary tokenization) muddier than it needs to be."""

PATH_PREFIX_MIN_COVERAGE = 0.60
"""HEURISTIC (session 04 spec): a candidate common path-prefix must cover at
least this fraction of a community's members to be trusted as its name --
below that, too many members live somewhere else entirely and the prefix
would be misleading."""

MAX_SUBSYSTEM_FINDINGS = 5
"""Anti-alert-fatigue cap (master-context.md sec 7), same discipline as every
other finding-emitting engine (e.g. RiskEngine's MAX_RISK_FINDINGS) -- applies
across BOTH finding kinds this engine emits (low_cohesion, god_subsystem)
combined, not five of each."""

LOW_COHESION_THRESHOLD = 0.5
LOW_COHESION_MIN_FILES = 5
LOW_COHESION_CONFIDENCE_DIVISOR = 20.0
"""HEURISTIC: confidence scales with file_count the same shape as
RiskEngine's ``risk_confidence = min(1.0, commit_count / 10)`` -- a
low-cohesion finding on a large subsystem is more likely to reflect a real
structural problem than the same cohesion score on a handful of files, which
could just be clustering noise around too little evidence."""

GOD_SUBSYSTEM_RATIO = 0.40
"""HEURISTIC (session 04 spec): a single subsystem holding more than this
fraction of the repo's files has effectively swallowed the whole codebase --
the partition isn't doing its job as a comprehension aid."""


@dataclass
class _Community:
    members: set[int]  # repo_paths.id
    forced_label: str | None = None
    forced_label_source: str | None = None


@dataclass
class _SubsystemComputation:
    """Everything SubsystemEngine needs to persist rows plus what
    ModuleCouplingEngine needs to compute the 'subsystem' granularity pass
    in the SAME stage, right after this one (see app/jobs/stages.py -- the
    two engines share a stage and must run in this explicit order, since
    module coupling at subsystem grain needs the partition this engine just
    computed)."""

    subsystem_rows: list[dict[str, Any]]
    member_rows_by_subsystem_index: list[list[dict[str, Any]]]
    path_to_subsystem_label: dict[int, str]  # path_id -> the label it landed in
    modularity: float


def _load_graph_and_files(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session
) -> tuple[nx.Graph, dict[int, File]]:
    """The combined, undirected, weighted graph every step of this engine
    operates over: every non-deleted file is a node (so orphans land in
    singleton communities rather than vanishing, per session 04 Part B step
    1), edges accumulate weight from BOTH structural dependencies
    (W_STRUCT per edge) and this run's coupling pairs (W_COUPLE *
    coupling_degree). Works entirely in integer path_id space -- no path
    string is resolved until a label is actually needed -- the same
    int-space-until-the-boundary discipline CouplingEngine already follows.
    """
    files = session.scalars(
        select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
    ).all()
    files_by_path_id = {f.path_id: f for f in files}

    graph: nx.Graph = nx.Graph()
    graph.add_nodes_from(files_by_path_id.keys())

    def _add_weight(a: int, b: int, weight: float) -> None:
        # Both endpoints must be real, live files -- a dependency/coupling
        # row pointing outside this node set (shouldn't happen given the
        # Facts layer's own conservatism, but never trusted blindly here)
        # is simply not added as an edge, never as a phantom node.
        if a == b or a not in files_by_path_id or b not in files_by_path_id:
            return
        if graph.has_edge(a, b):
            graph[a][b]["weight"] += weight
        else:
            graph.add_edge(a, b, weight=weight)

    for from_id, to_id in session.execute(
        select(Dependency.from_path_id, Dependency.to_path_id).where(Dependency.repo_id == repo_id)
    ).all():
        _add_weight(from_id, to_id, W_STRUCT)

    for a_id, b_id, degree in session.execute(
        select(Coupling.path_a_id, Coupling.path_b_id, Coupling.coupling_degree).where(
            Coupling.repo_id == repo_id, Coupling.analysis_run_id == run_id
        )
    ).all():
        _add_weight(a_id, b_id, W_COUPLE * degree)

    return graph, files_by_path_id


def _sort_communities(communities: list[_Community], path_map: dict[int, str]) -> list[_Community]:
    """Sorted by size desc, then by the sorted first member's path string
    (KNOWN HAZARD #1: seeding Louvain alone is not enough -- iterating an
    unordered community/set structure is the OTHER source of
    nondeterminism, and every place this engine touches a community list
    goes through this one sort)."""

    def _key(c: _Community) -> tuple[int, str]:
        first_path = min((path_map[m] for m in c.members), default="")
        return (-len(c.members), first_path)

    return sorted(communities, key=_key)


def _weights_to_targets(
    graph: nx.Graph, source: set[int], targets: list[_Community]
) -> list[float]:
    target_index: dict[int, int] = {}
    for i, community in enumerate(targets):
        for node in community.members:
            target_index[node] = i

    weights = [0.0] * len(targets)
    for node in source:
        if node not in graph:
            continue
        for neighbor, data in graph.adj[node].items():
            idx = target_index.get(neighbor)
            if idx is not None:
                weights[idx] += data.get("weight", 0.0)
    return weights


def _merge_small_communities(
    graph: nx.Graph, communities: list[_Community], path_map: dict[int, str]
) -> list[_Community]:
    """Session 04 Part B step 3: any community smaller than
    MIN_SUBSYSTEM_SIZE is folded into whichever OTHER community it has the
    most total edge weight to; a community with zero edge weight to
    anywhere else (a truly isolated small cluster) is instead collected into
    one final "Unclustered" bucket. Bounded loop: each iteration either
    strictly reduces the number of communities (a merge) or moves members
    into the unclustered pool and removes the source community -- both
    strictly shrink ``communities``, so this always terminates.
    """
    working = list(communities)
    unclustered: set[int] = set()

    while True:
        working = _sort_communities(working, path_map)
        small_idx = next(
            (i for i, c in enumerate(working) if len(c.members) < MIN_SUBSYSTEM_SIZE), None
        )
        if small_idx is None:
            break

        small = working.pop(small_idx)
        if not working:
            unclustered |= small.members
            continue

        weights = _weights_to_targets(graph, small.members, working)
        best_idx: int | None = None
        best_weight = 0.0
        for i, w in enumerate(weights):
            if w > best_weight:
                best_weight = w
                best_idx = i

        if best_idx is None:
            unclustered |= small.members
        else:
            working[best_idx].members |= small.members

    if unclustered:
        working.append(_Community(members=unclustered, forced_label="Unclustered"))

    return working


def _cap_subsystems(communities: list[_Community], path_map: dict[int, str]) -> list[_Community]:
    """Session 04 Part B step 3 / KNOWN HAZARD #6: capping must happen
    BEFORE naming, or the naming pass wastes work (and its uniqueness
    disambiguation) on communities that get thrown away immediately after.
    """
    if len(communities) <= MAX_SUBSYSTEMS:
        return _sort_communities(communities, path_map)

    ordered = _sort_communities(communities, path_map)
    kept = ordered[: MAX_SUBSYSTEMS - 1]
    remainder = ordered[MAX_SUBSYSTEMS - 1 :]

    other_members: set[int] = set()
    for c in remainder:
        other_members |= c.members
    kept.append(_Community(members=other_members, forced_label="Other"))
    return _sort_communities(kept, path_map)


def _common_dir_segments(paths: list[str]) -> list[list[str]]:
    return [p.split("/")[:-1] for p in paths]


def _path_prefix_label(members: set[int], path_map: dict[int, str]) -> str | None:
    """Session 04 Part B step 4a: the longest common directory-segment
    prefix that still covers at least PATH_PREFIX_MIN_COVERAGE of the
    community's members, scanning from the deepest possible depth down to 1
    -- coverage of a fixed candidate can only shrink as depth increases, so
    the first (deepest) depth that clears the threshold is, by construction,
    the LONGEST qualifying prefix. Depth 0 (the repository root) is never a
    candidate, satisfying "is not the repository root" for free.
    """
    paths = [path_map[m] for m in members]
    segment_lists = _common_dir_segments(paths)
    total = len(members)
    if total == 0:
        return None

    max_depth = max((len(segs) for segs in segment_lists), default=0)
    min_count = PATH_PREFIX_MIN_COVERAGE * total

    for depth in range(max_depth, 0, -1):
        candidates = Counter(tuple(segs[:depth]) for segs in segment_lists if len(segs) >= depth)
        if not candidates:
            continue
        prefix, count = candidates.most_common(1)[0]
        if count >= min_count:
            last = prefix[-1]
            if last in _GENERIC_DIR_SEGMENTS and len(prefix) >= 2:
                return f"{prefix[-2]}/{prefix[-1]}"
            return last
    return None


def _identifier_label(
    members: set[int],
    path_map: dict[int, str],
    symbol_names_by_path_id: dict[int, list[str]],
    used_labels: set[str],
) -> str | None:
    """Session 04 Part B step 4b. Tokens are gathered walking members in
    sorted-path order so that Counter.most_common's tie-breaking (stable,
    first-inserted-wins) is itself deterministic -- the raw query order rows
    arrive in from the DB is not guaranteed stable across runs."""
    tokens: list[str] = []
    for path_id in sorted(members, key=lambda m: path_map[m]):
        stem = PurePosixPath(path_map[path_id]).stem
        tokens.extend(tokenize_identifier(stem))
        for name in symbol_names_by_path_id.get(path_id, []):
            tokens.extend(tokenize_identifier(name))

    tokens = [t for t in tokens if t not in STOPWORDS]
    if not tokens:
        return None

    for token, _count in Counter(tokens).most_common():
        if token not in used_labels:
            return token
    return None


def _disambiguate(
    label: str, members: set[int], path_map: dict[int, str], used_labels: set[str]
) -> str:
    """KNOWN HAZARD #7: this must never loop. Two escalating attempts
    (append the community's most common top-level directory, then a plain
    numeric suffix) that are each guaranteed to eventually produce something
    unused, since a numeric suffix search is bounded by the (small, capped)
    number of subsystems in the run."""
    if label not in used_labels:
        return label

    top_level = Counter(path_map[m].split("/")[0] for m in members).most_common(1)
    if top_level:
        candidate = f"{label} ({top_level[0][0]})"
        if candidate not in used_labels:
            return candidate

    suffix = 2
    while f"{label} {suffix}" in used_labels:
        suffix += 1
    return f"{label} {suffix}"


def _name_communities(
    communities: list[_Community],
    path_map: dict[int, str],
    symbol_names_by_path_id: dict[int, list[str]],
) -> list[tuple[_Community, str, str]]:
    """Returns (community, label, label_source) triples in the SAME order as
    ``communities`` (already capped/sorted -- this function only names, it
    never reorders)."""
    used_labels: set[str] = set()
    result: list[tuple[_Community, str, str]] = []

    for index, community in enumerate(communities):
        if community.forced_label is not None:
            label, source = community.forced_label, "fallback"
        else:
            path_label = _path_prefix_label(community.members, path_map)
            if path_label is not None:
                label, source = path_label, "path_prefix"
            else:
                ident_label = _identifier_label(
                    community.members, path_map, symbol_names_by_path_id, used_labels
                )
                if ident_label is not None:
                    label, source = ident_label, "identifiers"
                else:
                    label, source = f"Subsystem {index + 1}", "fallback"

        label = _disambiguate(label, community.members, path_map, used_labels)
        used_labels.add(label)
        result.append((community, label, source))

    return result


def compute_subsystems(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session
) -> _SubsystemComputation:
    """Pure computation (no writes) -- the module-level ``compute_*`` core
    every engine follows (app/engines/base.py), independently testable and
    callable from ModuleCouplingEngine's subsystem-granularity pass without
    re-running the Louvain partition a second time in the same stage."""
    graph, files_by_path_id = _load_graph_and_files(repo_id, run_id, session)
    path_map = load_path_map(repo_id, session)

    if not files_by_path_id:
        return _SubsystemComputation(
            subsystem_rows=[],
            member_rows_by_subsystem_index=[],
            path_to_subsystem_label={},
            modularity=0.0,
        )

    raw_communities = nx.community.louvain_communities(
        graph, weight="weight", seed=LOUVAIN_SEED, resolution=LOUVAIN_RESOLUTION
    )
    # nx.community.modularity divides by 2*m (twice the total edge weight)
    # and raises ZeroDivisionError outright on an edgeless graph (verified
    # directly against this networkx version) -- a real, not hypothetical,
    # case here: a tiny repo with files but no detected imports/coupling at
    # all. Modularity is undefined with no edges to explain; 0.0 is the
    # honest "no signal" value, not a guess at what the score would be.
    modularity = (
        nx.community.modularity(graph, raw_communities, weight="weight")
        if graph.number_of_edges() > 0
        else 0.0
    )

    communities = [_Community(members=set(c)) for c in raw_communities]
    communities = _merge_small_communities(graph, communities, path_map)
    communities = _cap_subsystems(communities, path_map)

    symbol_rows = session.execute(
        select(Symbol.path_id, Symbol.name).where(Symbol.repo_id == repo_id)
    ).all()
    symbol_names_by_path_id: dict[int, list[str]] = {}
    for path_id, name in symbol_rows:
        symbol_names_by_path_id.setdefault(path_id, []).append(name)

    named = _name_communities(communities, path_map, symbol_names_by_path_id)

    total_files = len(files_by_path_id)
    subsystem_rows: list[dict[str, Any]] = []
    member_rows_by_subsystem_index: list[list[dict[str, Any]]] = []
    path_to_subsystem_label: dict[int, str] = {}

    pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_nodes() else {}

    for rank, (community, label, source) in enumerate(named):
        members = community.members
        internal_edges = 0
        external_edges = 0
        for node in members:
            if node not in graph:
                continue
            for neighbor in graph.adj[node]:
                if neighbor in members:
                    internal_edges += 1
                else:
                    external_edges += 1
        internal_edges //= 2  # each internal edge counted from both endpoints

        cohesion = (
            internal_edges / (internal_edges + external_edges)
            if (internal_edges + external_edges) > 0
            else 0.0
        )
        total_loc = sum(files_by_path_id[m].current_loc for m in members)

        subsystem_rows.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "label": label,
                "label_source": source,
                "file_count": len(members),
                "total_loc": total_loc,
                "internal_edges": internal_edges,
                "external_edges": external_edges,
                "cohesion": cohesion,
                "rank": rank,
                "_ratio_of_repo": len(members) / total_files if total_files else 0.0,
            }
        )
        member_rows_by_subsystem_index.append(
            [{"path_id": m, "centrality": pagerank.get(m, 0.0)} for m in members]
        )
        for m in members:
            path_to_subsystem_label[m] = label

    return _SubsystemComputation(
        subsystem_rows=subsystem_rows,
        member_rows_by_subsystem_index=member_rows_by_subsystem_index,
        path_to_subsystem_label=path_to_subsystem_label,
        modularity=modularity,
    )


_SEVERITY_WEIGHT = {Severity.high: 2, Severity.med: 1, Severity.low: 0}


def _subsystem_findings(
    repo_id: uuid.UUID, run_id: uuid.UUID, subsystem_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for row in subsystem_rows:
        if row["cohesion"] < LOW_COHESION_THRESHOLD and row["file_count"] >= LOW_COHESION_MIN_FILES:
            confidence = min(1.0, row["file_count"] / LOW_COHESION_CONFIDENCE_DIVISOR)
            candidates.append(
                {
                    "analysis_run_id": run_id,
                    "repo_id": repo_id,
                    "category": "architecture",
                    "severity": Severity.med,
                    "confidence": confidence,
                    "path_id": None,
                    "evidence_sha": None,
                    "title": f"Low-cohesion subsystem: {row['label']}",
                    "detail": (
                        f"cohesion={row['cohesion']:.2f} across {row['file_count']} files "
                        f"({row['internal_edges']} internal / {row['external_edges']} external edges)."
                    ),
                    "signature": finding_signature("architecture", f"low_cohesion:{row['label']}"),
                }
            )

        if row["_ratio_of_repo"] > GOD_SUBSYSTEM_RATIO:
            candidates.append(
                {
                    "analysis_run_id": run_id,
                    "repo_id": repo_id,
                    "category": "architecture",
                    "severity": Severity.high,
                    "confidence": min(1.0, row["_ratio_of_repo"]),
                    "path_id": None,
                    "evidence_sha": None,
                    "title": f"Dominant subsystem: {row['label']}",
                    "detail": (
                        f"{row['label']} contains {row['file_count']} files "
                        f"({row['_ratio_of_repo']:.0%} of the repository)."
                    ),
                    "signature": finding_signature("architecture", f"god_subsystem:{row['label']}"),
                }
            )

    candidates.sort(key=lambda f: (_SEVERITY_WEIGHT[f["severity"]], f["confidence"]), reverse=True)
    candidates = candidates[:MAX_SUBSYSTEM_FINDINGS]
    for rank, f in enumerate(candidates):
        f["rank"] = rank
    return candidates


class SubsystemEngine(Engine):
    """Deterministic subsystem decomposition (session 04, Part B):
    Louvain community detection over an undirected graph combining
    structural dependency edges and this run's coupling pairs, then a fixed
    post-processing pipeline (merge-small -> cap -> name) that turns a raw
    graph partition into something a person can actually read. See the
    module docstring constants above for exactly what's LOCKED vs HEURISTIC.

    Must run BEFORE ``ModuleCouplingEngine`` in the "subsystems" stage (both
    share one stage, see app/jobs/stages.py) -- that engine's
    ``subsystem``-granularity pass reads ``subsystem_members`` this engine
    just wrote.
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id
        computation = compute_subsystems(repo_id, run_id, session)

        subsystem_ids: list[int] = []
        for row, members in zip(
            computation.subsystem_rows, computation.member_rows_by_subsystem_index, strict=True
        ):
            insert_row = {k: v for k, v in row.items() if not k.startswith("_")}
            result = session.execute(insert(Subsystem).values(**insert_row).returning(Subsystem.id))
            subsystem_id = result.scalar_one()
            subsystem_ids.append(subsystem_id)
            if members:
                session.execute(
                    insert(SubsystemMember),
                    [{"subsystem_id": subsystem_id, **m} for m in members],
                )

        findings = _subsystem_findings(repo_id, run_id, computation.subsystem_rows)
        if findings:
            session.execute(insert(Finding), findings)

        largest = max(computation.subsystem_rows, key=lambda r: r["file_count"], default=None)

        return {
            "subsystems": len(computation.subsystem_rows),
            "largest": largest["label"] if largest else None,
            "modularity": computation.modularity,
        }
