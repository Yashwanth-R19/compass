from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Hit by the keep-alive ping every 10 minutes forever (Render's free
    tier spins down after 15 minutes idle, see DEPLOY.md) -- kept
    deliberately cheap: one trivial SELECT 1, which is also what proves the
    database itself is reachable, not just that the process is up."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": settings.COMPASS_VERSION, "db": "ok"}
