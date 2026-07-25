import uuid

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.db.models import Commit, CommitFile, Dependency, File
from app.db.wipe import wipe_repo_data
from app.ingestion.miner import MinedRepo
from app.languages.base import DependencyEdge


def persist_mined_repo(
    repo_id: uuid.UUID, mined: MinedRepo, dependencies: list[DependencyEdge], session: Session
) -> None:
    """Bulk-write mined commits/commit_files/files and structural
    dependency edges for ``repo_id``.

    ``dependencies`` is already-parsed by app/languages/scanner.py while the
    clone still existed (this function itself never touches the filesystem)
    — see jobs/runner.py's clone -> mine -> parse structure -> persist ->
    delete clone sequence. Always wipes existing repo-scoped rows first, in
    the same transaction as the inserts, so a re-run is a clean full replace
    rather than an accumulating merge — true on the very first ingestion too,
    where the wipe is a no-op. Caller commits; this function only stages the
    writes. This single wipe is also what makes it safe for the
    Coupling/Architecture/Overlay engines that run right after this, in the
    same job, to only INSERT — coupling/dependencies/findings for this
    repo_id are already empty by the time they run.
    """
    wipe_repo_data(repo_id, session)

    commit_id_by_sha: dict[str, uuid.UUID] = {c.sha: uuid.uuid4() for c in mined.commits}

    commit_rows = [
        {
            "id": commit_id_by_sha[c.sha],
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
        }
        for c in mined.commits
    ]
    if commit_rows:
        session.execute(insert(Commit), commit_rows)

    commit_file_rows = [
        {"id": uuid.uuid4(), "commit_id": commit_id_by_sha[c.sha], "file_path": path}
        for c in mined.commits
        for path in c.file_paths
    ]
    if commit_file_rows:
        session.execute(insert(CommitFile), commit_file_rows)

    file_rows = [
        {
            "id": uuid.uuid4(),
            "repo_id": repo_id,
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
            "id": uuid.uuid4(),
            "repo_id": repo_id,
            "from_path": edge.from_path,
            "to_path": edge.to_path,
            "dep_type": edge.dep_type,
        }
        for edge in dependencies
    ]
    if dependency_rows:
        session.execute(insert(Dependency), dependency_rows)
