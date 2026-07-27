import uuid

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import Commit, Dependency, File, RepoPath
from app.db.wipe import wipe_repo_data
from app.ingestion.miner import MinedRepo
from app.languages.base import DependencyEdge


def persist_mined_repo(
    repo_id: uuid.UUID, mined: MinedRepo, dependencies: list[DependencyEdge], session: Session
) -> None:
    """Bulk-write mined commits/files and structural dependency edges for
    ``repo_id``, interning every distinct path into ``repo_paths`` first so
    everything downstream references paths by integer id (Phase 1 schema
    diet).

    ``dependencies`` is already-parsed by app/languages/scanner.py while the
    clone still existed (this function itself never touches the filesystem)
    -- see jobs/runner.py's clone -> mine -> parse structure -> persist ->
    delete clone sequence. Always wipes existing repo-scoped rows first, in
    the same transaction as the inserts, so a re-run is a clean full replace
    rather than an accumulating merge -- true on the very first ingestion
    too, where the wipe is a no-op. Caller commits; this function only
    stages the writes. This single wipe is also what makes it safe for the
    Coupling/Architecture/Overlay engines that run right after this, in the
    same job, to only INSERT -- coupling/dependencies/findings for this
    repo_id are already empty by the time they run.

    Uses SQLAlchemy Core ``insert()`` with lists of dicts (bulk), not ORM
    object-per-row -- at 25k commits the ORM overhead is significant. Every
    identity-PK row omits ``id`` entirely and lets Postgres assign it.
    """
    wipe_repo_data(repo_id, session)

    all_paths: set[str] = set()
    for c in mined.commits:
        all_paths.update(c.file_paths)
    for f in mined.files:
        all_paths.add(f.path)
    for edge in dependencies:
        all_paths.add(edge.from_path)
        all_paths.add(edge.to_path)

    if all_paths:
        session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": p} for p in all_paths])

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
        }
        for edge in dependencies
    ]
    if dependency_rows:
        session.execute(insert(Dependency), dependency_rows)
