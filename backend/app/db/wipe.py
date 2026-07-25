import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Commit, CommitFile, Coupling, Dependency, File, FileMetrics, Finding


def wipe_repo_data(repo_id: uuid.UUID, session: Session) -> None:
    """Delete every repo-scoped row for ``repo_id``.

    Compass re-ingests/re-analyzes a repo by full delete-then-reinsert, never
    merge-by-path (see master-context.md sec 9, decision 6). This makes a
    re-run of ingestion or analysis idempotent: the second run's row counts
    always equal a single run's worth, never accumulate. File renames are
    therefore NOT tracked as continuity across runs — a rename is old-path
    deleted + new-path added on the next fresh run. This is a documented
    simplification, not a bug.

    Caller owns the transaction: this function only issues deletes, it does
    not commit. Wiping an already-empty repo_id (first-ever ingestion) is a
    harmless no-op.
    """
    file_ids_subq = select(File.id).where(File.repo_id == repo_id)
    commit_ids_subq = select(Commit.id).where(Commit.repo_id == repo_id)

    session.execute(delete(FileMetrics).where(FileMetrics.file_id.in_(file_ids_subq)))
    session.execute(delete(CommitFile).where(CommitFile.commit_id.in_(commit_ids_subq)))
    session.execute(delete(Coupling).where(Coupling.repo_id == repo_id))
    session.execute(delete(Dependency).where(Dependency.repo_id == repo_id))
    session.execute(delete(Finding).where(Finding.repo_id == repo_id))
    session.execute(delete(Commit).where(Commit.repo_id == repo_id))
    session.execute(delete(File).where(File.repo_id == repo_id))
