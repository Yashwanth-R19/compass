import os
import threading
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.ingestion.miner import IGNORE_DIRS, MAX_FILE_BYTES, infer_language
from app.languages.base import DependencyEdge, LanguageAnalyzer, Symbol
from app.languages.java_analyzer import JavaAnalyzer
from app.languages.javascript_analyzer import JavaScriptAnalyzer
from app.languages.python_analyzer import PythonAnalyzer

# Plugin registry: one LanguageAnalyzer per `files.language` value -- the
# registry key MUST match app/ingestion/miner.py::infer_language's output
# exactly, or that language's files are silently never scanned (no error,
# just an empty-looking result). "javascript" and "typescript" deliberately
# share the SAME JavaScriptAnalyzer instance (session 03, Part B) -- one
# class covers both, only the tree-sitter grammar picked per file extension
# differs -- so app/languages/scanner.py::_prepare_analyzers dedupes by
# instance identity to still call .prepare() exactly once for it.
_js_analyzer = JavaScriptAnalyzer()
LANGUAGE_ANALYZERS: dict[str, LanguageAnalyzer] = {
    "python": PythonAnalyzer(),
    "javascript": _js_analyzer,
    "typescript": _js_analyzer,
    "java": JavaAnalyzer(),
}

# Minified bundles checked into a repository are a real hazard for
# tree-sitter parse time -- this bounds how long any single file's
# extract_imports + extract_symbols is allowed to run before that file is
# abandoned (empty result) rather than stalling the whole structure stage.
# A thread + join(timeout), not signal.alarm, because SIGALRM doesn't exist
# on Windows and there is no portable way to hard-cancel a native parse call
# -- the abandoned thread may keep running in the background, but the
# caller moves on immediately either way.
_PARSE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class _FileScanResult:
    edges: list[tuple[str, str]]  # (target_path, import_kind)
    symbols: list[Symbol]


_EMPTY_FILE_RESULT = _FileScanResult(edges=[], symbols=[])


@dataclass(frozen=True)
class ScanResult:
    edges: list[DependencyEdge]
    symbols: list[tuple[str, Symbol]]  # (repo-relative path, Symbol)
    by_language: dict[str, dict[str, int]]  # language -> {"files", "edges", "symbols"}


def _prepare_analyzers(repo_root: str) -> None:
    """Calls ``.prepare(repo_root)`` exactly once per UNIQUE analyzer
    instance in THIS process -- deduping by identity, since "javascript"/
    "typescript" share one JavaScriptAnalyzer. Called directly for the
    inline (small-repo) path; for the parallel path it's what
    ``_worker_init`` runs inside each spawned worker process instead (see
    that function's docstring for why prepared state is rebuilt per-worker
    rather than sent from the parent)."""
    seen: set[int] = set()
    for analyzer in LANGUAGE_ANALYZERS.values():
        if id(analyzer) in seen:
            continue
        seen.add(id(analyzer))
        analyzer.prepare(repo_root)


def _worker_init(repo_root: str) -> None:
    """``ProcessPoolExecutor`` initializer -- runs exactly ONCE per spawned
    worker process, never per file. Performance fix (session 03, Part E):
    an earlier version of this scanner passed each file's already-prepared
    analyzer instance through the task tuple, which meant re-pickling
    JavaAnalyzer's class index (one entry per .java file in the repo) into
    EVERY single per-file task -- on a ~5,000-file synthetic benchmark this
    alone cost roughly 50 of the structure stage's ~80 measured seconds,
    blowing the 25s budget (plan/RULES.md sec 14). Rebuilding the index
    once per worker process here, and looking it up from the module-level
    ``LANGUAGE_ANALYZERS`` registry per task instead, means only small
    strings (a path, a language key) cross the process boundary per file.
    """
    _prepare_analyzers(repo_root)


def _scan_one_file(analyzer: LanguageAnalyzer, rel_path: str, repo_root: str) -> _FileScanResult:
    if isinstance(analyzer, JavaScriptAnalyzer):
        edges = analyzer.extract_import_edges(rel_path, repo_root)
    else:
        edges = [(target, "static") for target in analyzer.extract_imports(rel_path, repo_root)]
    symbols = analyzer.extract_symbols(rel_path, repo_root)
    return _FileScanResult(edges=edges, symbols=symbols)


def _scan_one_file_with_timeout(
    analyzer: LanguageAnalyzer, rel_path: str, repo_root: str
) -> _FileScanResult:
    box: list[_FileScanResult] = []

    def _run() -> None:
        box.append(_scan_one_file(analyzer, rel_path, repo_root))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(_PARSE_TIMEOUT_SECONDS)
    return box[0] if box else _EMPTY_FILE_RESULT


# (rel_path, repo_root, language) -- deliberately excludes the analyzer
# itself (see _worker_init's docstring for why): each worker process looks
# its own, already-prepared analyzer up from the module-level
# LANGUAGE_ANALYZERS registry by language key instead.
_ScanTask = tuple[str, str, str]


def _scan_file_worker(task: _ScanTask) -> tuple[str, str, _FileScanResult]:
    rel_path, repo_root, language = task
    analyzer = LANGUAGE_ANALYZERS[language]
    return rel_path, language, _scan_one_file_with_timeout(analyzer, rel_path, repo_root)


def _run_scan_tasks(
    repo_root: str, tasks: list[_ScanTask]
) -> list[tuple[str, str, _FileScanResult]]:
    """Below a small-repo threshold, runs inline -- spawning a process pool
    at all (Windows uses spawn, not fork) costs more than it saves, same
    reasoning as app/ingestion/miner.py::_analyze_files. The inline path
    prepares analyzers directly in this (the only) process; the parallel
    path prepares them once per worker via ``_worker_init`` instead (see its
    docstring) rather than in this parent process, since the parent never
    calls ``extract_imports``/``extract_symbols`` itself in that branch."""
    if not tasks:
        return []

    max_workers = min(4, os.cpu_count() or 1)
    if max_workers <= 1 or len(tasks) < 2 * max_workers:
        _prepare_analyzers(repo_root)
        return [
            (
                rel_path,
                language,
                _scan_one_file_with_timeout(LANGUAGE_ANALYZERS[language], rel_path, repo_root),
            )
            for rel_path, _repo_root, language in tasks
        ]

    chunksize = max(1, len(tasks) // (max_workers * 4))
    with ProcessPoolExecutor(
        max_workers=max_workers, initializer=_worker_init, initargs=(repo_root,)
    ) as executor:
        return list(executor.map(_scan_file_worker, tasks, chunksize=chunksize))


def extract_structural_edges(repo_root: str) -> ScanResult:
    """Walk the final checkout once and extract import edges + symbol
    declarations via registered LanguageAnalyzer plugins, tree-sitter
    parsing parallelized across a process pool (session 03, Part E).

    Runs during ingestion while the clone still exists -- the engines are
    DB-only and never touch the filesystem, so this is the one place
    structural parsing happens (see jobs/runner.py: clone -> mine -> parse
    structure -> persist -> delete clone).
    """
    root = Path(repo_root)
    tasks: list[_ScanTask] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            rel_path = (Path(dirpath) / fname).relative_to(root).as_posix()

            language = infer_language(rel_path)
            if language not in LANGUAGE_ANALYZERS:
                continue

            try:
                if (root / rel_path).stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue

            tasks.append((rel_path, repo_root, language))

    file_results = _run_scan_tasks(repo_root, tasks)

    edges: list[DependencyEdge] = []
    symbols: list[tuple[str, Symbol]] = []
    by_language: dict[str, dict[str, int]] = {}
    seen_edges: set[tuple[str, str]] = set()

    for rel_path, language, result in file_results:
        counts = by_language.setdefault(language, {"files": 0, "edges": 0, "symbols": 0})
        counts["files"] += 1

        for target, import_kind in result.edges:
            if target == rel_path:
                continue  # a resolved self-import isn't a real edge
            key = (rel_path, target)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append(
                DependencyEdge(
                    from_path=rel_path, to_path=target, dep_type="import", import_kind=import_kind
                )
            )
            counts["edges"] += 1

        for symbol in result.symbols:
            symbols.append((rel_path, symbol))
            counts["symbols"] += 1

    return ScanResult(edges=edges, symbols=symbols, by_language=by_language)
