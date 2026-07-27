import uuid
from pathlib import Path
from typing import Any

import networkx as nx
from sqlalchemy import insert, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Dependency, Finding, RepoPath, Severity
from app.db.paths import load_path_id_map
from app.engines.base import Engine

MAX_CYCLE_LENGTH = 10
"""``nx.simple_cycles``' ``length_bound`` -- caps how long a cycle we'll even
search for. Cycle enumeration is combinatorially expensive on a dense graph;
a cycle this long stops being a single actionable finding anyway."""

MAX_CYCLES_REPORTED = 50
"""Hard cap on how many cycle findings a single run writes, longest cycles
first -- keeps the findings stream itself from becoming the alert-fatigue
problem it exists to prevent (master-context.md sec 7) on a repo with a
genuinely tangled graph."""

LAYER_UI = "ui"
LAYER_SERVICE = "service"
LAYER_DB = "db"
LAYER_ORDER = {LAYER_UI: 0, LAYER_SERVICE: 1, LAYER_DB: 2}

LAYER_KEYWORDS: dict[str, set[str]] = {
    LAYER_UI: {"ui", "view", "views", "component", "components", "page", "pages", "frontend"},
    LAYER_SERVICE: {
        "service",
        "services",
        "logic",
        "domain",
        "usecase",
        "usecases",
        "controller",
        "controllers",
        "api",
    },
    LAYER_DB: {"db", "database", "model", "models", "repository", "repositories", "dao", "orm"},
}
"""Deliberately simple, path-convention-based layer guess -- allowed to be
conservative (master-context.md sec 8, Architecture Explorer row). Checks
directory segments and the filename stem against these keyword sets; the
first layer with a match wins (dict order: ui, service, db). A file matching
none of them is left unclassified and excluded from layering checks
entirely: this heuristic may under-report violations, it must never
fabricate one on a file it can't confidently place.
"""

_SEVERITY_WEIGHT = {Severity.high: 2, Severity.med: 1, Severity.low: 0}


def infer_layer(path: str) -> str | None:
    p = Path(path)
    segments = {seg.lower() for seg in p.parts[:-1]}
    segments.add(p.stem.lower())
    for layer, keywords in LAYER_KEYWORDS.items():
        if segments & keywords:
            return layer
    return None


def load_edges(repo_id: uuid.UUID, session: Session) -> list[tuple[str, str]]:
    """(from_path, to_path) string pairs -- resolved via a join through
    repo_paths (Phase 1 schema diet stores only from_path_id/to_path_id),
    since layer inference and cycle-finding both key off path strings."""
    from_path = aliased(RepoPath)
    to_path = aliased(RepoPath)
    rows = session.execute(
        select(from_path.path, to_path.path)
        .select_from(Dependency)
        .join(from_path, from_path.id == Dependency.from_path_id)
        .join(to_path, to_path.id == Dependency.to_path_id)
        .where(Dependency.repo_id == repo_id)
    ).all()
    return [(row[0], row[1]) for row in rows]


def build_graph(edges: list[tuple[str, str]]) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_edges_from(edges)
    return graph


def find_cycles(graph: nx.DiGraph) -> list[list[str]]:
    """Simple cycles in ``graph``, longest first, capped for large graphs
    (see MAX_CYCLE_LENGTH/MAX_CYCLES_REPORTED)."""
    cycles = list(nx.simple_cycles(graph, length_bound=MAX_CYCLE_LENGTH))
    cycles.sort(key=len, reverse=True)
    return cycles[:MAX_CYCLES_REPORTED]


def cycle_severity(length: int) -> Severity:
    if length >= 5:
        return Severity.high
    if length >= 3:
        return Severity.med
    return Severity.low


class ArchEngine(Engine):
    """Builds the structural dependency graph from ``dependencies`` and
    flags cycles + layering violations as findings.

    Pure DB-only: the clone is gone by the time this runs. Structural
    parsing happens exactly once, during ingestion, via
    ``app/languages/scanner.py``, which persists edges to ``dependencies``
    before the clone is deleted -- this engine only ever reads that table.
    """

    def run(self, repo_id: uuid.UUID, session: Session) -> dict[str, Any]:
        edges = load_edges(repo_id, session)
        graph = build_graph(edges)
        cycles = find_cycles(graph)
        violations = layering_violations(edges)
        path_id_map = load_path_id_map(repo_id, session)

        findings: list[dict[str, Any]] = [
            _cycle_finding(repo_id, cycle, path_id_map) for cycle in cycles
        ]
        findings += [
            _layering_finding(repo_id, from_path, to_path, kind, path_id_map)
            for from_path, to_path, kind in violations
        ]

        # Ranked by severity then size, most impactful first -- the
        # anti-alert-fatigue discipline (master-context.md sec 7).
        findings.sort(key=lambda f: (_SEVERITY_WEIGHT[f["severity"]], f["_size"]), reverse=True)
        for rank, finding in enumerate(findings):
            finding["rank"] = rank
            del finding["_size"]

        if findings:
            session.execute(insert(Finding), findings)

        return {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "cycles_found": len(cycles),
            "layering_violations_found": len(violations),
        }


def layering_violations(edges: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Returns (from_path, to_path, kind) for edges that violate the layer
    order ui -> service -> db, where kind is "skip" (ui importing db
    directly, jumping over service) or "inverted" (a lower layer importing a
    higher one, e.g. db importing service/ui, or service importing ui)."""
    violations: list[tuple[str, str, str]] = []
    for from_path, to_path in edges:
        from_layer, to_layer = infer_layer(from_path), infer_layer(to_path)
        if from_layer is None or to_layer is None or from_layer == to_layer:
            continue
        from_rank, to_rank = LAYER_ORDER[from_layer], LAYER_ORDER[to_layer]
        if from_layer == LAYER_UI and to_layer == LAYER_DB:
            violations.append((from_path, to_path, "skip"))
        elif from_rank > to_rank:
            violations.append((from_path, to_path, "inverted"))
    return violations


def _cycle_finding(
    repo_id: uuid.UUID, cycle: list[str], path_id_map: dict[str, int]
) -> dict[str, Any]:
    length = len(cycle)
    severity = cycle_severity(length)
    chain = " -> ".join([*cycle, cycle[0]])
    return {
        "repo_id": repo_id,
        "category": "architecture",
        "severity": severity,
        "confidence": 1.0,  # exact graph computation, not a statistical estimate
        "path_id": path_id_map[cycle[0]],
        "evidence_sha": None,
        "title": f"Circular dependency among {length} files",
        "detail": f"Import cycle: {chain}",
        "rank": 0,
        "_size": length,
    }


def layering_violation_severity(kind: str) -> Severity:
    return Severity.high if kind == "skip" else Severity.med


def _layering_finding(
    repo_id: uuid.UUID, from_path: str, to_path: str, kind: str, path_id_map: dict[str, int]
) -> dict[str, Any]:
    severity = layering_violation_severity(kind)
    if kind == "skip":
        title = "Layering violation: UI imports DB directly"
        detail = f"{from_path} (ui layer) imports {to_path} (db layer) directly, skipping the service layer."
    else:
        title = "Inverted layer dependency"
        detail = f"{from_path} imports {to_path}, but that dependency runs backwards through the ui/service/db layering."

    return {
        "repo_id": repo_id,
        "category": "architecture",
        "severity": severity,
        "confidence": 0.75,  # heuristic layer classification, not exact
        "path_id": path_id_map[from_path],
        "evidence_sha": None,
        "title": title,
        "detail": detail,
        "rank": 0,
        "_size": 0,
    }
