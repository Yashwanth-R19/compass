import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RepoPath


def load_path_map(repo_id: uuid.UUID, session: Session) -> dict[int, str]:
    """``repo_paths.id -> path`` for every path interned for ``repo_id``.

    The read-side counterpart of persist.py's intern step: engines and API
    handlers that only ever store/compare integer path ids (coupling,
    overlay, findings) use this to resolve back to a human-readable path
    string at the point they actually need one -- a finding's title/detail
    text, or an API response.
    """
    rows = session.execute(
        select(RepoPath.id, RepoPath.path).where(RepoPath.repo_id == repo_id)
    ).all()
    return {row.id: row.path for row in rows}


def load_path_id_map(repo_id: uuid.UUID, session: Session) -> dict[str, int]:
    """``path -> repo_paths.id`` for every path interned for ``repo_id`` --
    the reverse of load_path_map, for callers that start from a path string
    (e.g. ArchEngine, whose graph/layer logic is string-based) and need the
    id to reference in a findings row."""
    rows = session.execute(
        select(RepoPath.path, RepoPath.id).where(RepoPath.repo_id == repo_id)
    ).all()
    return {row.path: row.id for row in rows}
