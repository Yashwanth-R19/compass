from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import EntryPoint, File, RepoManifest, Symbol
from app.engines.base import Engine

if TYPE_CHECKING:
    from app.engines.context import RunContext

# ---- Config (module-level, documented; not per-caller knobs) ----

MANIFEST_CONFIDENCE = 0.95
CONVENTIONAL_CONFIDENCE = 0.75
TEST_ROOT_CONFIDENCE = 0.9
GRAPH_INFERRED_CONFIDENCE = 0.5
"""HEURISTIC confidences, session 04 spec: a manifest explicitly declaring
"run this file" is close to certain; a conventional filename is a strong but
not absolute convention; a graph-shape inference (no inbound imports, several
outbound) is the weakest, most indirect signal of the four."""

GRAPH_INFERRED_MIN_OUT_DEGREE = 3
GRAPH_INFERRED_CAP = 10
"""Session 04 spec: the graph-inferred rule's OWN candidate pool is capped
and ranked by out-degree BEFORE merging with every other rule's candidates --
a repo can have dozens of zero-inbound-import files (any script meant to be
run directly), and only the ones with the most outbound structure are likely
real entry points rather than small, unrelated utility scripts."""

MAX_ENTRY_POINTS = 20
"""Anti-alert-fatigue cap (master-context.md sec 7) on the FINAL, deduplicated,
cross-rule list -- distinct from GRAPH_INFERRED_CAP, which only bounds one
rule's contribution before merging."""

TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__", "spec"})

CONVENTIONAL_PY_BASENAMES: dict[str, str] = {
    "main.py": "cli",
    "__main__.py": "cli",
    "cli.py": "cli",
    "manage.py": "cli",
    "app.py": "web_server",
    "wsgi.py": "web_server",
    "asgi.py": "web_server",
}
"""Matched by BASENAME at any depth (unlike the JS/TS table below, which
matches full paths) -- Python entry-point files are routinely nested inside
a package directory, not just at the repo root."""

CONVENTIONAL_EXACT_PATHS: dict[str, str] = {
    "src/main.ts": "ui_root",
    "src/main.tsx": "ui_root",
    "src/main.js": "ui_root",
    "src/main.jsx": "ui_root",
    "src/index.ts": "ui_root",
    "src/index.tsx": "ui_root",
    "src/index.js": "ui_root",
    "src/index.jsx": "ui_root",
    "pages/_app.tsx": "ui_root",
    "pages/_app.jsx": "ui_root",
    "app/layout.tsx": "ui_root",
    "server.ts": "web_server",
    "server.js": "web_server",
}
"""Matched by EXACT repo-relative path, per session 04 Part D -- these are
framework bootstrap conventions (Vite/CRA/Next.js/a bare Node server) tied to
a specific location, not a basename that could legitimately appear anywhere."""

_CONFIG_FILE_STEMS = frozenset(
    {
        "webpack.config", "vite.config", "rollup.config", "babel.config",
        "jest.config", "eslint.config", "postcss.config", "tailwind.config",
        "vitest.config", "next.config", "svelte.config",
    }
)  # fmt: skip
"""HEURISTIC: excludes common JS/TS build-tool config files from the
graph-inferred rule. A bundler/lint config routinely imports several plugins
(out_degree >= 3) while nothing else in the repo ever imports IT (in_degree
0) -- a textbook false positive for "no inbound imports, several outbound"
despite being build tooling, not something a person runs directly."""


@dataclass
class _Candidate:
    path_id: int
    kind: str
    evidence: str
    confidence: float
    out_degree: int = 0


def _normalize_candidate_path(value: str) -> str:
    v = value.strip().strip("'\"")
    v = v.lstrip("./")
    while v.startswith("/"):
        v = v[1:]
    return v


def _resolve_bare_path(value: str, path_id_by_path: dict[str, int]) -> int | None:
    return path_id_by_path.get(_normalize_candidate_path(value))


def _resolve_token_in_text(text: str, path_id_by_path: dict[str, int]) -> int | None:
    """Best-effort, conservative resolution for a shell-command-shaped
    string (a package.json script, a Dockerfile CMD/ENTRYPOINT, a Procfile
    line): tokenize on whitespace and take the FIRST token that exactly
    matches a real, currently-existing repo path -- never a fuzzy or partial
    match, per the governing "a missed edge is fine, a fabricated one isn't"
    rule every conservative resolver in this codebase follows."""
    cleaned = text.replace("[", " ").replace("]", " ").replace(",", " ")
    for raw_token in cleaned.split():
        token = _normalize_candidate_path(raw_token)
        if token in path_id_by_path:
            return path_id_by_path[token]
    return None


def _resolve_python_console_script(target: str, path_id_by_path: dict[str, int]) -> int | None:
    """``pyproject.toml``'s ``[project.scripts]``/poetry ``scripts`` values
    are ``"package.module:function"`` strings, not file paths -- converts the
    dotted module portion to the file it names (``pkg.cli`` -> ``pkg/cli.py``,
    falling back to ``pkg/cli/__init__.py`` for a package)."""
    module_part = target.split(":", 1)[0].strip()
    if not module_part:
        return None
    as_module = module_part.replace(".", "/") + ".py"
    if as_module in path_id_by_path:
        return path_id_by_path[as_module]
    as_package = module_part.replace(".", "/") + "/__init__.py"
    return path_id_by_path.get(as_package)


def _resolve_java_fqcn(fqcn: str, path_id_by_path: dict[str, int]) -> int | None:
    return path_id_by_path.get(fqcn.replace(".", "/") + ".java")


def _manifest_candidates(
    repo_id: uuid.UUID, session: Session, path_id_by_path: dict[str, int]
) -> list[_Candidate]:
    """Session 04 Part D, "Manifest-declared" rule. Reads ``repo_manifests``
    (session 03's already-extracted, small, named field set -- never the raw
    file) and resolves each referenced target against the CURRENT file set;
    a reference that doesn't resolve to a real file produces NO candidate at
    all, never a guessed one."""
    candidates: list[_Candidate] = []
    rows = session.execute(
        select(RepoManifest.kind, RepoManifest.data).where(RepoManifest.repo_id == repo_id)
    ).all()

    for kind, data in rows:
        if kind == "package_json":
            scripts = data.get("scripts")
            if isinstance(scripts, dict):
                for name, entry_kind in (
                    ("dev", "web_server"),
                    ("start", "web_server"),
                    ("build", "build"),
                ):
                    value = scripts.get(name)
                    if not isinstance(value, str):
                        continue
                    path_id = _resolve_token_in_text(value, path_id_by_path)
                    if path_id is not None:
                        candidates.append(
                            _Candidate(
                                path_id,
                                entry_kind,
                                f"package.json scripts.{name} references this file",
                                MANIFEST_CONFIDENCE,
                            )
                        )
            for entry_field in ("main", "module"):
                value = data.get(entry_field)
                if not isinstance(value, str):
                    continue
                path_id = _resolve_bare_path(value, path_id_by_path)
                if path_id is not None:
                    candidates.append(
                        _Candidate(
                            path_id,
                            "cli",
                            f"package.json {entry_field} references this file",
                            MANIFEST_CONFIDENCE,
                        )
                    )

        elif kind == "pyproject":
            script_sources = [data.get("scripts")]
            poetry = data.get("poetry")
            if isinstance(poetry, dict):
                script_sources.append(poetry.get("scripts"))
            for source in script_sources:
                if not isinstance(source, dict):
                    continue
                for target in source.values():
                    if not isinstance(target, str):
                        continue
                    path_id = _resolve_python_console_script(target, path_id_by_path)
                    if path_id is not None:
                        candidates.append(
                            _Candidate(
                                path_id,
                                "cli",
                                "pyproject.toml [project.scripts] references this file",
                                MANIFEST_CONFIDENCE,
                            )
                        )

        elif kind == "dockerfile":
            for instruction in ("CMD", "ENTRYPOINT"):
                for value in data.get(instruction) or []:
                    path_id = _resolve_token_in_text(value, path_id_by_path)
                    if path_id is not None:
                        candidates.append(
                            _Candidate(
                                path_id,
                                "web_server",
                                f"Dockerfile {instruction}",
                                MANIFEST_CONFIDENCE,
                            )
                        )

        elif kind == "procfile":
            for line in data.get("lines") or []:
                _process_type, _, command = line.partition(":")
                command = command.strip() or line
                path_id = _resolve_token_in_text(command, path_id_by_path)
                if path_id is not None:
                    candidates.append(
                        _Candidate(
                            path_id,
                            "web_server",
                            "Procfile references this file",
                            MANIFEST_CONFIDENCE,
                        )
                    )

        elif kind == "pom_xml":
            main_class = data.get("mainClass")
            if isinstance(main_class, str):
                path_id = _resolve_java_fqcn(main_class, path_id_by_path)
                if path_id is not None:
                    candidates.append(
                        _Candidate(path_id, "cli", "pom.xml mainClass", MANIFEST_CONFIDENCE)
                    )

    return candidates


def _conventional_candidates(files: Sequence[File]) -> list[_Candidate]:
    """Session 04 Part D, "Conventional filename" rule (Python/JS-TS halves;
    Java's ``main`` method is handled separately in ``_java_main_candidates``,
    which shares this rule's confidence)."""
    candidates: list[_Candidate] = []
    for f in files:
        basename = PurePosixPath(f.path).name
        py_kind = CONVENTIONAL_PY_BASENAMES.get(basename)
        if py_kind is not None:
            candidates.append(
                _Candidate(
                    f.path_id,
                    py_kind,
                    f"conventional filename: {basename}",
                    CONVENTIONAL_CONFIDENCE,
                )
            )
        exact_kind = CONVENTIONAL_EXACT_PATHS.get(f.path)
        if exact_kind is not None:
            candidates.append(
                _Candidate(
                    f.path_id,
                    exact_kind,
                    f"conventional filename: {f.path}",
                    CONVENTIONAL_CONFIDENCE,
                )
            )
    return candidates


def _java_main_candidates(repo_id: uuid.UUID, session: Session) -> list[_Candidate]:
    """Session 04 Part D: "For Java: any file with a symbols row of
    kind='method' and name='main' (session 03 guarantees this)." Also
    requires ``exported`` -- session 03's own guarantee is specifically that
    a ``public static void main`` produces ``exported=True`` with no
    special-casing (CLAUDE.md), so checking it here is the literal target of
    that guarantee, not an extra invented condition.
    """
    rows = session.execute(
        select(Symbol.path_id).where(
            Symbol.repo_id == repo_id,
            Symbol.kind == "method",
            Symbol.name == "main",
            Symbol.exported.is_(True),
        )
    ).all()
    return [
        _Candidate(path_id, "cli", "Java public static void main method", CONVENTIONAL_CONFIDENCE)
        for (path_id,) in rows
    ]


def _test_root_candidates(files: Sequence[File]) -> list[_Candidate]:
    """Session 04 Part D, "Test roots" rule: groups every ``is_test`` file
    (session 03's shared classifier, never re-derived here) by its
    qualifying test directory, then reports ONE representative file per
    directory -- not every file -- since ``entry_points.path_id`` FKs
    ``repo_paths``, which only interns FILE paths; there is no row to
    reference for a bare directory string. The representative is the
    alphabetically-first path in the group, a fixed, deterministic pick.

    A file under a literally-named test directory (``tests/``, ``test/``,
    ``__tests__/``, ``spec/``, at any depth) groups by the path UP TO AND
    INCLUDING the shallowest such segment; a file that's classified
    ``is_test`` without such a directory in its path (e.g. a bare
    ``test_utils.py`` living in an ordinary package directory) groups by its
    own immediate containing directory instead.
    """
    groups: dict[str, list[File]] = {}
    for f in files:
        if not f.is_test:
            continue
        segments = f.path.split("/")[:-1]
        key = None
        for i, seg in enumerate(segments):
            if seg in TEST_DIR_NAMES:
                key = "/".join(segments[: i + 1])
                break
        if key is None:
            key = "/".join(segments) if segments else "(root)"
        groups.setdefault(key, []).append(f)

    candidates = []
    for directory in sorted(groups):
        representative = min(groups[directory], key=lambda f: f.path)
        candidates.append(
            _Candidate(
                representative.path_id,
                "test_root",
                f"test directory: {directory}/",
                TEST_ROOT_CONFIDENCE,
            )
        )
    return candidates


def _is_config_file(path: str) -> bool:
    return PurePosixPath(path).stem in _CONFIG_FILE_STEMS


def _graph_inferred_candidates(graph: Any, files_by_path: dict[str, File]) -> list[_Candidate]:
    """Session 04 Part D, "Graph-inferred" rule: in-degree 0 (nothing in the
    repo imports it) and out-degree >= GRAPH_INFERRED_MIN_OUT_DEGREE (it
    imports enough of the codebase to plausibly be a real composition root,
    not a leaf utility), excluding test files and heuristically-recognized
    build-tool config files. Capped and ranked by out-degree BEFORE this
    rule's candidates are merged with every other rule's (GRAPH_INFERRED_CAP)."""
    candidates: list[_Candidate] = []
    for path, f in files_by_path.items():
        if f.is_test or _is_config_file(path):
            continue
        if path not in graph:
            continue
        if graph.in_degree(path) == 0 and graph.out_degree(path) >= GRAPH_INFERRED_MIN_OUT_DEGREE:
            out_degree = graph.out_degree(path)
            candidates.append(
                _Candidate(
                    f.path_id,
                    "graph_inferred",
                    f"no inbound imports, {out_degree} outbound",
                    GRAPH_INFERRED_CONFIDENCE,
                    out_degree=out_degree,
                )
            )
    candidates.sort(key=lambda c: (-c.out_degree, c.path_id))
    return candidates[:GRAPH_INFERRED_CAP]


def compute_entry_points(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session, ctx: RunContext
) -> list[dict[str, Any]]:
    """Pure computation (no writes) -- reads ``repo_manifests``/
    ``dependencies``/``symbols``/``files`` only, no filesystem access (all
    of Facts, none of it live). Reuses ``ctx.dependency_graph`` rather than
    rebuilding it -- ``EntryPointEngine`` runs in the same "architecture"
    stage as ``ArchEngine``, right after it, so the graph is already cached
    on this SAME ``ctx`` instance (session 01's RunContext discipline).
    """
    files = session.scalars(
        select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
    ).all()
    path_id_by_path = {f.path: f.path_id for f in files}
    files_by_path = {f.path: f for f in files}

    graph = ctx.dependency_graph(session)

    all_candidates: list[_Candidate] = []
    all_candidates += _manifest_candidates(repo_id, session, path_id_by_path)
    all_candidates += _conventional_candidates(files)
    all_candidates += _java_main_candidates(repo_id, session)
    all_candidates += _test_root_candidates(files)
    all_candidates += _graph_inferred_candidates(graph, files_by_path)

    # Deduplicate to one row per path, keeping the HIGHEST-confidence
    # detection -- ties (same confidence from two different rules) keep
    # whichever was seen first in the fixed processing order above, never
    # decided by DB iteration order.
    best_by_path: dict[int, _Candidate] = {}
    for c in all_candidates:
        existing = best_by_path.get(c.path_id)
        if existing is None or c.confidence > existing.confidence:
            best_by_path[c.path_id] = c

    ordered = sorted(best_by_path.values(), key=lambda c: (-c.confidence, -c.out_degree, c.path_id))
    ordered = ordered[:MAX_ENTRY_POINTS]

    return [
        {
            "analysis_run_id": run_id,
            "repo_id": repo_id,
            "path_id": c.path_id,
            "kind": c.kind,
            "evidence": c.evidence,
            "confidence": c.confidence,
            "rank": rank,
        }
        for rank, c in enumerate(ordered)
    ]


class EntryPointEngine(Engine):
    """Deterministic entry-point detection (session 04, Part D): four
    independent rules (manifest-declared, conventional filename, graph-
    inferred, test roots), deduplicated to one row per file keeping the
    highest-confidence detection. Runs between ``ArchEngine`` and
    ``OverlayEngine`` inside the "architecture" stage (see
    app/jobs/stages.py) -- reads that engine's dependency graph off the
    shared ``ctx`` rather than rebuilding it, and writes no findings of its
    own (Part D doesn't specify any).
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        rows = compute_entry_points(ctx.repo_id, ctx.run_id, session, ctx)
        if rows:
            session.execute(insert(EntryPoint), rows)
        return {"entry_points": len(rows)}
