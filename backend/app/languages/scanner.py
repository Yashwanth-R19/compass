import os
from pathlib import Path

from app.ingestion.miner import IGNORE_DIRS, MAX_FILE_BYTES, infer_language
from app.languages.base import DependencyEdge, LanguageAnalyzer
from app.languages.python_analyzer import PythonAnalyzer

# Plugin registry: one LanguageAnalyzer per `files.language` value. Adding
# Java/JS/TS later is registering a new analyzer here -- nothing downstream
# (persist, ArchEngine, overlay) needs to change (master-context.md sec 9,
# decision 3).
LANGUAGE_ANALYZERS: dict[str, LanguageAnalyzer] = {
    "python": PythonAnalyzer(),
}


def extract_structural_edges(repo_root: str) -> list[DependencyEdge]:
    """Walk the final checkout and extract import edges via registered
    LanguageAnalyzer plugins.

    Runs during ingestion while the clone still exists -- ArchEngine and the
    overlay engine are DB-only and never touch the filesystem, so this is
    the one place structural parsing happens (see jobs/runner.py: clone ->
    mine -> parse structure -> persist -> delete clone).
    """
    root = Path(repo_root)
    edges: list[DependencyEdge] = []
    seen: set[tuple[str, str]] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            rel_path = (Path(dirpath) / fname).relative_to(root).as_posix()

            analyzer = LANGUAGE_ANALYZERS.get(infer_language(rel_path))
            if analyzer is None:
                continue

            try:
                if (root / rel_path).stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue

            for target in analyzer.extract_imports(rel_path, repo_root):
                if target == rel_path:
                    continue  # a resolved self-import isn't a real edge
                key = (rel_path, target)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(DependencyEdge(from_path=rel_path, to_path=target, dep_type="import"))

    return edges
