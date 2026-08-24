import uuid
from datetime import datetime

from pydantic import BaseModel


class ShareLinkOut(BaseModel):
    slug: str
    created_at: datetime


class SharedRunOut(BaseModel):
    """What ``GET /shared/{slug}`` resolves a slug to -- repo_id + run_id
    ONLY (session 02, Part E). A share link grants access to one run, not to
    the repository; the frontend re-requests repo metadata/analysis data
    itself, passing ``?run_id=<this run_id>&share=<slug>`` so
    ``require_repo_access`` can verify the same thing again on each of
    those requests -- this endpoint's job is just the slug -> ids lookup."""

    repo_id: uuid.UUID
    run_id: uuid.UUID
