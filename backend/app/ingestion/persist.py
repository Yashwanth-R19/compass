import uuid
from pathlib import PurePosixPath

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import Commit, Dependency, File, RepoManifest, RepoPath
from app.db.models import Symbol as SymbolRow
from app.db.wipe import wipe_facts
from app.ingestion.manifests import ManifestRow
from app.ingestion.miner import MinedRepo
from app.languages.base import DependencyEdge, Symbol

_JS_TEST_DIR_SEGMENTS = {"__tests__", "test", "tests", "e2e", "cypress"}


def classify_is_test(path: str, language: str) -> bool:
    """Whether ``path`` (repo-relative, posix separators) is a test file --
    session 03's ONE shared classifier, populated into ``files.is_test``
    here and reused (never reimplemented) by session 07's test-gap
    analysis, so the two never define "is this a test file" differently.

    Python: under a /tests/ or /test/ directory at any depth, or the file
    stem matches ``test_*``/``*_test``, or the file is ``conftest.py``.
    JS/TS: the filename contains ``.test.`` or ``.spec.``, or the path is
    under a ``__tests__``/``test``/``tests``/``e2e``/``cypress`` directory
    at any depth.
    Java: under a ``src/test/`` directory, or the stem ends in ``Test``,
    ``Tests``, or ``IT``.
    Any other language: never classified as a test file.
    """
    p = PurePosixPath(path)
    segments = p.parts
    stem = p.stem

    if language == "python":
        if "tests" in segments or "test" in segments:
            return True
        if stem == "conftest":
            return True
        return stem.startswith("test_") or stem.endswith("_test")

    if language in ("javascript", "typescript"):
        if ".test." in p.name or ".spec." in p.name:
            return True
        return any(segment in _JS_TEST_DIR_SEGMENTS for segment in segments)

    if language == "java":
        if any(
            segments[i] == "src" and segments[i + 1] == "test" for i in range(len(segments) - 1)
        ):
            return True
        return stem.endswith(("Test", "Tests", "IT"))

    return False


def persist_facts(
    repo_id: uuid.UUID,
    mined: MinedRepo,
    dependencies: list[DependencyEdge],
    symbols: list[tuple[str, Symbol]],
    manifests: list[ManifestRow],
    session: Session,
) -> None:
    """Bulk-write mined commits/files, structural dependency edges, symbols,
    and manifests for ``repo_id`` -- the "persist_facts" stage
    (app/jobs/stages.py), run only when the miner actually ran (i.e.
    head_sha changed; see app/jobs/runner.py's reuse-facts check).

    Wipes and fully replaces commits/files/dependencies/symbols/
    repo_manifests via ``wipe_facts``, but INTERNS PATHS IDEMPOTENTLY: only
    paths not already present for this repo_id are inserted into
    ``repo_paths``, and existing paths keep their existing ids. This is what
    makes ``repo_paths`` safe to leave out of ``wipe_facts`` (see its
    docstring) -- older analysis runs' Insight rows (coupling/findings/
    file_metrics) reference paths by these same, stable ids, so a path that
    exists in both the old and new head_sha must resolve to the same
    integer id across runs, or every old run's Insight data would silently
    point at the wrong (or a deleted) file.

    ``dependencies``/``symbols`` are already-parsed by
    app/languages/scanner.py, and ``manifests`` by
    app/ingestion/manifests.py, all while the clone still existed (this
    function itself never touches the filesystem) -- see
    jobs/runner.py's clone -> mine -> parse structure -> persist -> delete
    clone sequence. Caller commits; this function only stages the writes.

    Uses SQLAlchemy Core ``insert()`` with lists of dicts (bulk), not ORM
    object-per-row -- at 25k commits the ORM overhead is significant. Every
    identity-PK row omits ``id`` entirely and lets Postgres assign it.
    """
    wipe_facts(repo_id, session)

    all_paths: set[str] = set()
    for c in mined.commits:
        all_paths.update(c.file_paths)
    for f in mined.files:
        all_paths.add(f.path)
    for edge in dependencies:
        all_paths.add(edge.from_path)
        all_paths.add(edge.to_path)
    for path, _symbol in symbols:
        all_paths.add(path)
    for manifest in manifests:
        all_paths.add(manifest.path)

    existing_paths = set(
        session.scalars(select(RepoPath.path).where(RepoPath.repo_id == repo_id)).all()
    )
    new_paths = all_paths - existing_paths
    if new_paths:
        session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": p} for p in new_paths])

    path_id_by_path: dict[str, int] = {
        row.path: row.id
        for row in session.execute(
            select(RepoPath.id, RepoPath.path).where(RepoPath.repo_id == repo_id)
        ).all()
    }

    commit_rows = [
        {
            "repo_id": repo_id,
            "sha": c.sha,
            "author_name": c.author_name,
            "author_email": c.author_email,
            "committed_at": c.committed_at,
            "message": c.message,
            "is_fix": c.is_fix,
            "is_revert": c.is_revert,
            "files_changed": c.files_changed,
            "insertions": c.insertions,
            "deletions": c.deletions,
            "changed_path_ids": [path_id_by_path[p] for p in c.file_paths],
            "added_lines": list(c.file_added_lines),
            "deleted_lines": list(c.file_deleted_lines),
        }
        for c in mined.commits
    ]
    if commit_rows:
        session.execute(insert(Commit), commit_rows)

    file_rows = [
        {
            "repo_id": repo_id,
            "path_id": path_id_by_path[f.path],
            "path": f.path,
            "language": f.language,
            "current_loc": f.current_loc,
            "complexity": f.complexity,
            "churn_total": f.churn_total,
            "commit_count": f.commit_count,
            "first_seen": f.first_seen,
            "last_seen": f.last_seen,
            "is_deleted": f.is_deleted,
            "is_test": classify_is_test(f.path, f.language),
        }
        for f in mined.files
    ]
    if file_rows:
        session.execute(insert(File), file_rows)

    dependency_rows = [
        {
            "repo_id": repo_id,
            "from_path_id": path_id_by_path[edge.from_path],
            "to_path_id": path_id_by_path[edge.to_path],
            "dep_type": edge.dep_type,
            "import_kind": edge.import_kind,
        }
        for edge in dependencies
    ]
    if dependency_rows:
        session.execute(insert(Dependency), dependency_rows)

    symbol_rows = [
        {
            "repo_id": repo_id,
            "path_id": path_id_by_path[path],
            "name": symbol.name,
            "kind": symbol.kind,
            "line": symbol.line,
            "exported": symbol.exported,
        }
        for path, symbol in symbols
    ]
    if symbol_rows:
        session.execute(insert(SymbolRow), symbol_rows)

    manifest_rows = [
        {
            "repo_id": repo_id,
            "path_id": path_id_by_path[manifest.path],
            "kind": manifest.kind,
            "data": manifest.data,
        }
        for manifest in manifests
    ]
    if manifest_rows:
        session.execute(insert(RepoManifest), manifest_rows)
