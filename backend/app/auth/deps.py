"""Auth dependencies (session 02, Part C/D): who the request is, and whether
it may read a given repo's analysis data.

``require_repo_access`` is the ONE reusable dependency plan/RULES.md sec 9
requires on every repo-scoped endpoint -- ``backend/tests/test_access_control.py``
enumerates every route under ``/repos/{`` and asserts each one depends on it.
Never re-implement this check inline in a route handler.
"""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.session import SESSION_COOKIE_NAME, decode_session_token
from app.db.base import get_db
from app.db.models import Repo, ShareLink, User
from app.db.runs import resolve_run_id


def has_repo_scope(user: User) -> bool:
    """Whether the user has the GitHub repo scope."""
    if not user.token_scopes:
        return False

    scopes = {
        scope.strip()
        for scope in user.token_scopes.replace(",", " ").split()
        if scope.strip()
    }

    return "repo" in scopes


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Returns the authenticated ``User`` for this request, or ``None`` if
    there is no session cookie, the cookie fails signature/expiry
    verification, or ``sub`` no longer resolves to an existing user row
    (e.g. the account was deleted after the cookie was issued). Never
    raises -- this is the dependency for endpoints that work anonymously."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    user_id = decode_session_token(token)
    if user_id is None:
        return None
    return db.get(User, user_id)


def current_user_required(
    user: User | None = Depends(current_user_optional),
) -> User:
    """Same verification as ``current_user_optional``, but raises 401 when
    there is no valid session -- for endpoints that only make sense for a
    logged-in user (``GET /auth/me``, ``GET /me/repos``, share-link
    creation, ...)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


def require_repo_access(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    share: str | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
) -> Repo:
    """Gates every repo-scoped endpoint (plan/RULES.md sec 9):

    - a public repo is readable by anyone;
    - a private repo is readable only by ``repo.owner_user_id``, or by a
      request carrying a valid, unrevoked share-link ``?share=<slug>`` whose
      linked run is exactly the run this request resolves to (an explicit
      ``?run_id=`` if given, else ``repo.current_run_id``/latest -- the same
      resolution ``app/db/runs.py::resolve_run_id`` gives the endpoint
      itself). This is what makes "a share link grants access to one run,
      not to the repository" (CLAUDE.md) hold for every endpoint uniformly,
      including ones like ``/status``/``/runs`` that aren't themselves
      scoped to a single run -- a share link for an older, superseded run
      does not unlock those, only the specific analysis endpoints for that
      exact run.

    Returns the ``Repo`` row (so callers that already need it, e.g.
    ``GET /repos/{id}``, don't have to look it up twice) or raises 404 (repo
    doesn't exist) / 403 (exists but this request may not read it).
    """
    repo = db.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repo not found.")

    if not repo.is_private:
        return repo

    if user is not None and repo.owner_user_id is not None and user.id == repo.owner_user_id:
        return repo

    if share:
        link = db.scalar(select(ShareLink).where(ShareLink.slug == share))
        if link is not None and link.revoked_at is None:
            resolved_run_id = resolve_run_id(repo, run_id, db)
            if resolved_run_id is not None and link.run_id == resolved_run_id:
                return repo

    raise HTTPException(
        status_code=403,
        detail="This repository is private. Connect private repositories to view it.",
    )


__all__ = [
    "current_user_optional",
    "current_user_required",
    "has_repo_scope",
    "require_repo_access",
]
