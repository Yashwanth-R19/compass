"""The Map's diagram builder -- ``GET /repos/{id}/diagram``.

A READ-TIME aggregation of rows Compass has already computed and persisted:
live files and import edges (Facts), plus this run's subsystem partition,
entry points, hidden dependencies and cycles (Insight, or recomputed from
Facts exactly the way ``/architecture`` and ``/hidden-dependencies`` already
do). It computes nothing new about the code -- it groups, counts, and orders.
There is no LLM anywhere in this module (the optional AI labelling layer is
``app/narrative/diagram_ai.py``, which only adds text to this output).

**Deterministic by construction:** every list is sorted before it leaves this
module and no set/dict is ever iterated unsorted on the way to the response,
so the same run and grouping always produce a byte-identical response.

Two groupings share one pipeline:

- ``subsystem`` -- one group per persisted ``Subsystem`` row (Louvain
  communities, already capped at 12 by SubsystemEngine).
- ``folder`` -- one group per directory, split deterministically until no
  single folder dominates (see ``_folder_groups``), capped at
  ``MAX_TOP_GROUPS`` with the remainder folded into an "Other" bucket.

Layers (the Map's horizontal bands) come from the group-level import graph:
strongly connected components are condensed, then the DAG is layered with
``networkx.topological_generations`` -- generation 0 is code nothing else
imports, the last is code that is imported but imports nothing internal.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlparse

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.diagram_infra import detect_actor, detect_infra
from app.db.models import (
    AnalysisRun,
    Dependency,
    DependencyDeclared,
    EntryPoint,
    File,
    Repo,
    RepoPath,
    Subsystem,
    SubsystemMember,
)
from app.engines.context import RunContext
from app.schemas.diagram import (
    DiagramActorOut,
    DiagramCapsOut,
    DiagramEntryPointOut,
    DiagramFileOut,
    DiagramGroupEdgeOut,
    DiagramGroupOut,
    DiagramHiddenGroupEdgeOut,
    DiagramHiddenPairOut,
    DiagramInfraOut,
    DiagramLayerOut,
    DiagramResponse,
    DiagramSourceOut,
    DiagramStatsOut,
    LayerKind,
)

# ---- Caps and thresholds (module-level, documented; not per-caller knobs) ----

MAX_TOP_GROUPS = 16
"""HEURISTIC: the most groups the Map draws at top level. Subsystem mode is
already capped at 12 upstream; folder mode folds the smallest excess folders
into one "Other" bucket beyond this. A person can't read 40 boxes at once."""

MAX_CHILDREN_VISIBLE = 12
"""HEURISTIC, enforced by the frontend (echoed in ``caps``): how many
children an expanded group/folder shows before the rest collapse behind a
"+N more" chip."""

MAX_IMPORT_EDGES = 25_000
"""Infra cap on how many file-level import pairs one response ships. Beyond
this the list is truncated in a documented priority order (cycle edges,
then cross-group, then intra-group) and ``stats.imports_truncated`` is set,
which the UI discloses -- never a silent partial graph."""

FOLDER_SPLIT_DOMINANCE = 0.5
"""HEURISTIC: keep splitting the largest folder group while it holds more
than this fraction of all files (a repo that is 90% ``src/`` would otherwise
render as one useless box)."""

FOLDER_MIN_GROUPS = 3
"""HEURISTIC: also keep splitting while there are fewer than this many
groups."""

FOLDER_MAX_SPLIT_ITERATIONS = 64
"""Bound on the folder-split loop (each iteration strictly deepens one
group, so it always terminates anyway; this is a belt-and-braces bound)."""

MAX_LAYERS = 8
"""HEURISTIC: the most connected bands drawn; deeper generations are merged
into the last band."""

FOLDER_LABEL_MAX_CHARS = 28
"""Folder labels longer than this show only their last two segments."""

UNASSIGNED_GROUP_ID = "sub:unassigned"
OTHER_GROUP_ID = "other"


@dataclass
class _Group:
    id: str
    label: str
    label_source: str
    base_path: str
    members: list[int] = field(default_factory=list)
    cohesion: float | None = None
    internal_edges: int | None = None
    external_edges: int | None = None
    folded_count: int = 0


def _caps() -> DiagramCapsOut:
    return DiagramCapsOut(
        max_top_groups=MAX_TOP_GROUPS,
        max_children_visible=MAX_CHILDREN_VISIBLE,
        max_import_edges=MAX_IMPORT_EDGES,
        folder_split_dominance=FOLDER_SPLIT_DOMINANCE,
        folder_min_groups=FOLDER_MIN_GROUPS,
    )


def source_links(repo_url: str, head_sha: str | None) -> DiagramSourceOut:
    """Blob/tree base URLs pinned to the analysed commit, so a link always
    opens exactly what was analysed (never a later version of the file)."""
    base = repo_url.strip().rstrip("/")
    if base.endswith(".git"):
        base = base[: -len(".git")]
    host_name = urlparse(base).netloc.lower()
    if host_name.startswith("www."):
        host_name = host_name[len("www.") :]
    if head_sha and host_name == "github.com":
        return DiagramSourceOut(
            host="github",
            head_sha=head_sha,
            blob_base_url=f"{base}/blob/{head_sha}/",
            tree_base_url=f"{base}/tree/{head_sha}/",
        )
    if head_sha and host_name == "gitlab.com":
        return DiagramSourceOut(
            host="gitlab",
            head_sha=head_sha,
            blob_base_url=f"{base}/-/blob/{head_sha}/",
            tree_base_url=f"{base}/-/tree/{head_sha}/",
        )
    host = (
        "github"
        if host_name == "github.com"
        else "gitlab" if host_name == "gitlab.com" else "other"
    )
    return DiagramSourceOut(host=host, head_sha=head_sha, blob_base_url=None, tree_base_url=None)


def _empty_response(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    grouping: str,
    source: DiagramSourceOut,
    facts_archived: bool,
) -> DiagramResponse:
    return DiagramResponse(
        repo_id=repo_id,
        run_id=run_id,
        grouping="folder" if grouping == "folder" else "subsystem",
        facts_archived=facts_archived,
        source=source,
        groups=[],
        group_edges=[],
        hidden_group_edges=[],
        layers=[],
        infra=[],
        actor=None,
        files=[],
        imports=[],
        hidden_pairs=[],
        cycles=[],
        stats=DiagramStatsOut(
            file_count=0,
            group_count=0,
            import_edge_count=0,
            hidden_pair_count=0,
            cycle_count=0,
            imports_truncated=False,
            other_folded_count=0,
        ),
        caps=_caps(),
    )


def _dir_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def common_dir_prefix(paths: list[str]) -> str:
    """Longest common DIRECTORY prefix, segment-wise ("" if none)."""
    if not paths:
        return ""
    split = [_dir_of(p).split("/") if _dir_of(p) else [] for p in paths]
    prefix = split[0]
    for segs in split[1:]:
        n = 0
        while n < len(prefix) and n < len(segs) and prefix[n] == segs[n]:
            n += 1
        prefix = prefix[:n]
        if not prefix:
            break
    return "/".join(prefix)


# ---- Folder grouping ---------------------------------------------------------


def _folder_label(prefix: str) -> str:
    if len(prefix) <= FOLDER_LABEL_MAX_CHARS:
        return prefix
    return "…/" + "/".join(prefix.split("/")[-2:])


def _split_bucket(key: str, members: list[int], paths: list[str]) -> dict[str, list[int]]:
    """One level below directory ``key``: ``key/<seg>`` for files in a
    deeper folder, ``key/`` for files directly inside ``key``."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for i in members:
        rest = paths[i][len(key) + 1 :]
        sub = f"{key}/{rest.split('/')[0]}" if "/" in rest else f"{key}/"
        buckets[sub].append(i)
    return dict(buckets)


def folder_groups(paths: list[str]) -> list[_Group]:
    """Deterministic directory grouping. ``paths`` must be sorted; members are
    indices into it. Bucket keys: ``""`` (root files), ``"P"`` (everything
    under ``P/``), ``"P/"`` (files directly inside ``P``, created only when
    ``P`` is split)."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, path in enumerate(paths):
        groups["" if "/" not in path else path.split("/")[0]].append(i)
    total = len(paths)

    for _ in range(FOLDER_MAX_SPLIT_ITERATIONS):
        if len(groups) >= MAX_TOP_GROUPS:
            break
        candidates = sorted(
            (k for k in groups if k != "" and not k.endswith("/")),
            key=lambda k: (-len(groups[k]), k),
        )
        chosen: tuple[str, dict[str, list[int]]] | None = None
        for k in candidates:
            buckets = _split_bucket(k, groups[k], paths)
            only_direct = len(buckets) == 1 and next(iter(buckets)).endswith("/")
            if not only_direct:
                chosen = (k, buckets)
                break
        if chosen is None:
            break
        key, buckets = chosen
        need = len(groups) < FOLDER_MIN_GROUPS or len(groups[key]) / total > FOLDER_SPLIT_DOMINANCE
        if not need:
            break
        del groups[key]
        groups.update(buckets)

    other: list[int] = []
    folded = 0
    if len(groups) > MAX_TOP_GROUPS:
        ordered = sorted(groups, key=lambda k: (-len(groups[k]), k))
        for k in ordered[MAX_TOP_GROUPS - 1 :]:
            other.extend(groups.pop(k))
            folded += 1

    result: list[_Group] = []
    for key in sorted(groups):
        if key == "":
            label, base = "(root files)", ""
        elif key.endswith("/"):
            label, base = f"{_folder_label(key[:-1])} (files)", key[:-1]
        else:
            label, base = _folder_label(key), key
        result.append(_Group(f"dir:{key}", label, "path", base, sorted(groups[key])))
    if other:
        result.append(
            _Group(
                OTHER_GROUP_ID,
                f"Other ({folded} folders)",
                "fallback",
                "",
                sorted(other),
                folded_count=folded,
            )
        )
    return result


# ---- Subsystem grouping ------------------------------------------------------


def _subsystem_groups(
    run_id: uuid.UUID,
    files: list[File],
    index_by_path_id: dict[int, int],
    db: Session,
) -> tuple[list[_Group], dict[int, float]] | None:
    """``None`` when the run has no subsystem rows at all (caller falls back
    to folder grouping)."""
    subsystems = db.scalars(
        select(Subsystem).where(Subsystem.analysis_run_id == run_id).order_by(Subsystem.rank)
    ).all()
    if not subsystems:
        return None

    by_id = {s.id: s for s in subsystems}
    groups_by_sub: dict[int, _Group] = {
        s.id: _Group(
            f"sub:{s.rank}",
            s.label,
            s.label_source,
            "",
            cohesion=s.cohesion,
            internal_edges=s.internal_edges,
            external_edges=s.external_edges,
        )
        for s in subsystems
    }
    centrality: dict[int, float] = {}
    assigned: set[int] = set()
    rows = db.execute(
        select(SubsystemMember.subsystem_id, SubsystemMember.path_id, SubsystemMember.centrality)
        .where(SubsystemMember.subsystem_id.in_(list(by_id)))
        .order_by(SubsystemMember.subsystem_id, SubsystemMember.path_id)
    ).all()
    for subsystem_id, path_id, member_centrality in rows:
        i = index_by_path_id.get(path_id)
        if i is None or i in assigned:
            continue
        assigned.add(i)
        groups_by_sub[subsystem_id].members.append(i)
        centrality[i] = member_centrality

    result = [groups_by_sub[s.id] for s in subsystems if groups_by_sub[s.id].members]
    unassigned = [i for i in range(len(files)) if i not in assigned]
    if unassigned:
        result.append(_Group(UNASSIGNED_GROUP_ID, "Unassigned", "fallback", "", unassigned))
    for g in result:
        g.members.sort()
        g.base_path = common_dir_prefix([files[i].path for i in g.members])
    return result, centrality


# ---- Layers ------------------------------------------------------------------


@dataclass
class _LayerPlan:
    layers: list[tuple[LayerKind, str, list[str]]]  # connected + standalone bands only
    in_group_cycle: set[str]
    cyclic_edges: set[tuple[str, str]]


def compute_layers(group_ids: list[str], edges: list[tuple[str, str]]) -> _LayerPlan:
    """Group-level bands from import direction (see module docstring)."""
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(sorted(group_ids))
    graph.add_edges_from(sorted(edges))

    in_cycle: set[str] = set()
    scc_of: dict[str, int] = {}
    for n, component in enumerate(
        sorted((sorted(c) for c in nx.strongly_connected_components(graph)), key=lambda c: c[0])
    ):
        for g in component:
            scc_of[g] = n
        if len(component) > 1:
            in_cycle.update(component)
    cyclic_edges = {(a, b) for a, b in edges if a in in_cycle and scc_of[a] == scc_of[b]}

    standalone = sorted(g for g in group_ids if graph.degree(g) == 0)
    connected = graph.subgraph([g for g in group_ids if graph.degree(g) > 0]).copy()

    generations: list[list[str]] = []
    if connected.number_of_nodes() > 0:
        condensed = nx.condensation(connected)
        for generation in nx.topological_generations(condensed):
            members: list[str] = []
            for node in generation:
                members.extend(condensed.nodes[node]["members"])
            generations.append(sorted(members))
    if len(generations) > MAX_LAYERS:
        merged = [g for gen in generations[MAX_LAYERS - 1 :] for g in gen]
        generations = generations[: MAX_LAYERS - 1] + [sorted(merged)]

    layers: list[tuple[LayerKind, str, list[str]]] = []
    if len(generations) == 1:
        layers.append(("connected", "Connected code", generations[0]))
    elif len(generations) >= 2:
        for k, members in enumerate(generations):
            if k == 0:
                layers.append(("surface", "Surface", members))
            elif k == len(generations) - 1:
                layers.append(("foundation", "Foundation", members))
            else:
                layers.append(("middle", f"Layer {k + 1}", members))
    if standalone:
        layers.append(("standalone", "Standalone", standalone))
    return _LayerPlan(layers=layers, in_group_cycle=in_cycle, cyclic_edges=cyclic_edges)


# ---- Entry point -------------------------------------------------------------


def build_diagram(repo: Repo, run_id: uuid.UUID, grouping: str, db: Session) -> DiagramResponse:
    run = db.get(AnalysisRun, run_id)
    source = source_links(repo.url, run.head_sha if run is not None else None)

    if repo.facts_evicted_at is not None:
        return _empty_response(repo.id, run_id, grouping, source, facts_archived=True)

    files = list(
        db.scalars(
            select(File)
            .where(File.repo_id == repo.id, File.is_deleted.is_(False))
            .order_by(File.path)
        ).all()
    )
    if not files:
        return _empty_response(repo.id, run_id, grouping, source, facts_archived=False)

    paths = [f.path for f in files]
    index_by_path_id = {f.path_id: i for i, f in enumerate(files)}
    index_by_path = {p: i for i, p in enumerate(paths)}

    # Imports: deduplicated (from, to) file-index pairs between live files.
    import_set: set[tuple[int, int]] = set()
    for from_id, to_id in db.execute(
        select(Dependency.from_path_id, Dependency.to_path_id).where(Dependency.repo_id == repo.id)
    ).all():
        a = index_by_path_id.get(from_id)
        b = index_by_path_id.get(to_id)
        if a is not None and b is not None and a != b:
            import_set.add((a, b))
    imports = sorted(import_set)

    ctx = RunContext(repo_id=repo.id, run_id=run_id)

    hidden_best: dict[tuple[int, int], tuple[float, int]] = {}
    for h in ctx.hidden_dependencies(db):
        a = index_by_path_id.get(h["path_a_id"])
        b = index_by_path_id.get(h["path_b_id"])
        if a is None or b is None or a == b:
            continue
        key = (min(a, b), max(a, b))
        current = hidden_best.get(key)
        if current is None or h["coupling_degree"] > current[0]:
            hidden_best[key] = (h["coupling_degree"], h["shared_revs"])
    hidden_pairs = [
        DiagramHiddenPairOut(a=a, b=b, degree=deg, shared_revs=revs)
        for (a, b), (deg, revs) in sorted(hidden_best.items())
    ]

    cycles: list[list[int]] = []
    for cycle in ctx.cycles(db):
        indices = [index_by_path.get(p) for p in cycle]
        if all(i is not None for i in indices) and len(indices) >= 2:
            cycles.append([i for i in indices if i is not None])
    cycle_edges: set[tuple[int, int]] = set()
    for c in cycles:
        for k in range(len(c)):
            cycle_edges.add((c[k], c[(k + 1) % len(c)]))

    entry_rows = db.scalars(
        select(EntryPoint)
        .where(EntryPoint.analysis_run_id == run_id)
        .order_by(EntryPoint.rank, EntryPoint.id)
    ).all()
    entry_points: list[tuple[int, EntryPoint]] = []
    for ep in entry_rows:
        i = index_by_path_id.get(ep.path_id)
        if i is not None:
            entry_points.append((i, ep))

    # ---- Grouping ----
    centrality: dict[int, float] = {}
    groups: list[_Group]
    subsystem_result = (
        _subsystem_groups(run_id, files, index_by_path_id, db) if grouping == "subsystem" else None
    )
    if subsystem_result is not None:
        groups, centrality = subsystem_result
        if len(groups) > MAX_TOP_GROUPS:
            # Defensive only -- SubsystemEngine already caps at 12.
            ordered = sorted(groups, key=lambda g: (-len(g.members), g.id))
            kept, rest = ordered[: MAX_TOP_GROUPS - 1], ordered[MAX_TOP_GROUPS - 1 :]
            folded_members = sorted(i for g in rest for i in g.members)
            kept.append(
                _Group(
                    OTHER_GROUP_ID,
                    f"Other ({len(rest)} groups)",
                    "fallback",
                    common_dir_prefix([paths[i] for i in folded_members]),
                    folded_members,
                    folded_count=len(rest),
                )
            )
            groups = kept
    else:
        # Folder mode -- or subsystem mode on a run with zero subsystem rows,
        # which honestly falls back to directories rather than inventing a
        # partition (the response still says grouping="subsystem").
        groups = folder_groups(paths)

    group_of: list[str] = [""] * len(files)
    for g in groups:
        for i in g.members:
            group_of[i] = g.id

    # ---- Group edges ----
    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    for a, b in imports:
        ga, gb = group_of[a], group_of[b]
        if ga != gb:
            edge_counts[(ga, gb)] += 1
    file_cycle_group_edges = {
        (group_of[a], group_of[b]) for a, b in cycle_edges if group_of[a] != group_of[b]
    }

    plan = compute_layers([g.id for g in groups], list(edge_counts))

    hidden_groups: dict[tuple[str, str], list[DiagramHiddenPairOut]] = defaultdict(list)
    for pair in hidden_pairs:
        ga, gb = group_of[pair.a], group_of[pair.b]
        if ga != gb:
            hidden_groups[(min(ga, gb), max(ga, gb))].append(pair)
    hidden_group_edges = [
        DiagramHiddenGroupEdgeOut(
            a=a,
            b=b,
            pair_count=len(items),
            max_degree=max(p.degree for p in items),
            total_shared_revs=sum(p.shared_revs for p in items),
        )
        for (a, b), items in sorted(hidden_groups.items())
    ]

    # ---- Infra and actor ----
    group_of_path = {paths[i]: group_of[i] for i in range(len(files))}
    declared_rows = db.execute(
        select(DependencyDeclared.ecosystem, DependencyDeclared.package_name, RepoPath.path)
        .join(RepoPath, RepoPath.id == DependencyDeclared.manifest_path_id)
        .where(DependencyDeclared.repo_id == repo.id, DependencyDeclared.is_direct.is_(True))
    ).all()
    infra: list[DiagramInfraOut] = detect_infra(
        paths,
        [(row[0], row[1], row[2]) for row in declared_rows],
        [(paths[i], ep.evidence) for i, ep in entry_points],
        group_of_path,
    )
    actor: DiagramActorOut | None = detect_actor(
        [(paths[i], ep.kind) for i, ep in entry_points], group_of_path
    )

    # ---- Bands, top to bottom ----
    group_size = {g.id: len(g.members) for g in groups}

    def _band_sort(ids: list[str]) -> list[str]:
        return sorted(ids, key=lambda gid: (-group_size.get(gid, 0), gid))

    layers: list[DiagramLayerOut] = []
    if actor is not None:
        layers.append(DiagramLayerOut(index=0, kind="actor", label="Callers", group_ids=["actor"]))
    layer_of: dict[str, int] = {}
    for kind, label, members in plan.layers:
        index = len(layers)
        for gid in members:
            layer_of[gid] = index
        layers.append(
            DiagramLayerOut(index=index, kind=kind, label=label, group_ids=_band_sort(members))
        )
    if infra:
        layers.append(
            DiagramLayerOut(
                index=len(layers),
                kind="infra",
                label="Infrastructure & delivery",
                group_ids=sorted(item.id for item in infra),
            )
        )

    # ---- Group payloads ----
    entry_by_group: dict[str, list[DiagramEntryPointOut]] = defaultdict(list)
    for i, ep in entry_points:
        entry_by_group[group_of[i]].append(
            DiagramEntryPointOut(
                file_index=i,
                path=paths[i],
                kind=ep.kind,
                evidence=ep.evidence,
                confidence=ep.confidence,
            )
        )

    group_out: list[DiagramGroupOut] = []
    for g in groups:
        member_files = [files[i] for i in g.members]
        group_out.append(
            DiagramGroupOut(
                id=g.id,
                label=g.label,
                label_source=g.label_source,
                base_path=g.base_path,
                layer=layer_of.get(g.id, 0),
                file_count=len(member_files),
                total_loc=sum(f.current_loc for f in member_files),
                churn_365d=sum(f.churn_recent_365d for f in member_files),
                commit_count=sum(f.commit_count for f in member_files),
                last_changed=max((int(f.last_seen.timestamp()) for f in member_files), default=0),
                cohesion=g.cohesion,
                internal_edges=g.internal_edges,
                external_edges=g.external_edges,
                entry_points=entry_by_group.get(g.id, []),
                in_group_cycle=g.id in plan.in_group_cycle,
                folded_count=g.folded_count,
            )
        )
    group_out.sort(key=lambda g: (g.layer, -g.file_count, g.id))

    group_edges = [
        DiagramGroupEdgeOut(
            source=a,
            target=b,
            import_count=count,
            in_file_cycle=(a, b) in file_cycle_group_edges,
            in_group_cycle=(a, b) in plan.cyclic_edges,
        )
        for (a, b), count in sorted(edge_counts.items())
    ]

    # ---- Imports truncation (documented priority order) ----
    import_edge_count = len(imports)
    imports_truncated = import_edge_count > MAX_IMPORT_EDGES
    if imports_truncated:
        tier_cycle = [e for e in imports if e in cycle_edges]
        tier_cross = [
            e for e in imports if e not in cycle_edges and group_of[e[0]] != group_of[e[1]]
        ]
        tier_intra = [
            e for e in imports if e not in cycle_edges and group_of[e[0]] == group_of[e[1]]
        ]
        imports = sorted((tier_cycle + tier_cross + tier_intra)[:MAX_IMPORT_EDGES])

    files_out = [
        DiagramFileOut(
            i=i,
            path=f.path,
            group_id=group_of[i],
            loc=f.current_loc,
            churn_365d=f.churn_recent_365d,
            commit_count=f.commit_count,
            last_changed=int(f.last_seen.timestamp()),
            language=f.language,
            is_test=f.is_test,
            centrality=centrality.get(i) if subsystem_result is not None else None,
        )
        for i, f in enumerate(files)
    ]

    return DiagramResponse(
        repo_id=repo.id,
        run_id=run_id,
        grouping="folder" if grouping == "folder" else "subsystem",
        facts_archived=False,
        source=source,
        groups=group_out,
        group_edges=group_edges,
        hidden_group_edges=hidden_group_edges,
        layers=layers,
        infra=infra,
        actor=actor,
        files=files_out,
        imports=[[a, b] for a, b in imports],
        hidden_pairs=hidden_pairs,
        cycles=cycles,
        stats=DiagramStatsOut(
            file_count=len(files),
            group_count=len(group_out),
            import_edge_count=import_edge_count,
            hidden_pair_count=len(hidden_pairs),
            cycle_count=len(cycles),
            imports_truncated=imports_truncated,
            other_folded_count=sum(g.folded_count for g in groups),
        ),
        caps=_caps(),
    )
