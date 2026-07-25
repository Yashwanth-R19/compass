import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import RepoStatus


class RepoCreate(BaseModel):
    url: str


class RepoCreateResponse(BaseModel):
    repo_id: uuid.UUID
    job_id: uuid.UUID


class RepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    owner: str
    name: str
    default_branch: str | None
    status: RepoStatus
    commit_count: int
    analyzed_at: datetime | None
    created_at: datetime
    file_count: int


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_id: uuid.UUID | None
    job_type: str
    status: str
    progress: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None
