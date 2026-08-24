"""Share links (session 02, Part E): a share link grants read access to ONE
analysis run, never to the repository -- see ``ShareLink``'s docstring in
app/db/models.py and ``require_repo_access`` in app/auth/deps.py, which is
what actually enforces that on every repo-scoped read.

Not repo-scoped (``/runs/{run_id}/share``, ``/shared/{slug}``), so these
routes are deliberately outside ``test_access_control.py``'s
``/repos/{``-enumeration sweep -- their own access rule ("only the run's
repo owner may create/revoke") is enforced inline here instead, since it's
a different check (ownership of the run's repo, not "can this request read
this repo").
"""

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user_required
from app.db.base import get_db
from app.db.models import AnalysisRun, Repo, ShareLink, User
from app.schemas.share import SharedRunOut, ShareLinkOut

router = APIRouter()


def _generate_slug() -> str:
    return secrets.token_urlsafe(12)


def _require_run_owner(run_id: uuid.UUID, user: User, db: Session) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    repo = db.get(Repo, run.repo_id)
    if repo is None or repo.owner_user_id != user.id:
        raise HTTPException(
            status_code=403, detail="Only the repository's owner may manage share links for it."
        )
    return run


@router.post("/runs/{run_id}/share", response_model=ShareLinkOut, status_code=201)
def create_share_link(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user_required),
) -> ShareLinkOut:
    _require_run_owner(run_id, user, db)

    # Idempotent: at most one ACTIVE share link per run -- re-clicking
    # "share" returns the same slug rather than minting duplicates that
    # would all need separate revocation.
    existing = db.scalar(
        select(ShareLink).where(ShareLink.run_id == run_id, ShareLink.revoked_at.is_(None))
    )
    if existing is not None:
        return ShareLinkOut(slug=existing.slug, created_at=existing.created_at)

    link = ShareLink(run_id=run_id, slug=_generate_slug(), created_by=user.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return ShareLinkOut(slug=link.slug, created_at=link.created_at)


@router.delete("/runs/{run_id}/share")
def revoke_share_link(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user_required),
) -> dict:
    _require_run_owner(run_id, user, db)

    active_links = db.scalars(
        select(ShareLink).where(ShareLink.run_id == run_id, ShareLink.revoked_at.is_(None))
    ).all()
    now = datetime.now(UTC)
    for link in active_links:
        link.revoked_at = now
    db.commit()
    return {"status": "ok"}


@router.get("/shared/{slug}", response_model=SharedRunOut)
def resolve_shared_link(slug: str, db: Session = Depends(get_db)) -> SharedRunOut:
    """Unauthenticated by design -- this is exactly the endpoint an
    anonymous visitor with a share link hits. Revoked or unknown slugs both
    404 identically (no signal to distinguish "never existed" from
    "revoked")."""
    link = db.scalar(select(ShareLink).where(ShareLink.slug == slug))
    if link is None or link.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Share link not found.")

    run = db.get(AnalysisRun, link.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Share link not found.")

    return SharedRunOut(repo_id=run.repo_id, run_id=run.id)


__all__ = ["router"]
