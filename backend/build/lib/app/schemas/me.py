import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models import AnalysisRunStatus, RepoStatus


class MyRepoOut(BaseModel):
    id: uuid.UUID
    url: str
    owner: str
    name: str
    is_private: bool
    status: RepoStatus
    latest_run_status: AnalysisRunStatus | None
    analyzed_at: datetime | None
    health_score: float | None


class MyReposResponse(BaseModel):
    repos: list[MyRepoOut]
    page: int
    per_page: int
    total: int


class GithubRepoOut(BaseModel):
    full_name: str
    private: bool
    size: int
    language: str | None
    pushed_at: str | None


class MyGithubReposResponse(BaseModel):
    repos: list[GithubRepoOut]
    # True when the 100-per-page / 3-page cap (session 02, Part E) was hit,
    # meaning this account may have more repositories than are listed here.
    truncated: bool
