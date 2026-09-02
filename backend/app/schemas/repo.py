import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.models import AnalysisRunStatus, RepoStatus, StageStatus


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
    is_private: bool
    is_showcase: bool


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


class StageOut(BaseModel):
    """One ``analysis_stages`` row, as the frontend's stage-pill strip reads
    it (Phase 02, CLAUDE.md). ``summary`` is the small JSONB teaser payload
    a stage leaves behind (e.g. {"commits": 4182}); ``None`` until the stage
    is at least running."""

    name: str
    status: StageStatus
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    summary: dict[str, Any] | None


class RepoStatusResponse(BaseModel):
    """The single endpoint the frontend polls (Part E). Deliberately cheap:
    one lookup for the repo's latest run, one query on analysis_stages, no
    joins into any result table (coupling/findings/risk/health).

    ``current_run_id`` (distinct from ``run_id``, the LATEST run regardless
    of outcome) is what lets the frontend tell "this repo has never had a
    successful run" (null) apart from "the latest re-analysis attempt
    failed, but a previous good run still exists" (set) -- the former needs
    a blocking failure state, the latter must keep showing the last-good
    run's data (RepoLayout.tsx)."""

    repo_id: uuid.UUID
    repo_status: RepoStatus
    current_run_id: uuid.UUID | None
    run_id: uuid.UUID | None
    run_status: AnalysisRunStatus | None
    run_error: str | None
    stages: list[StageOut]
    # Session 16, Part B: True the moment app/jobs/eviction.py has wiped this
    # repo's Facts for being unvisited past FACTS_TTL_DAYS -- the repo row
    # and its current run's Insight (health/risk/passport/...) are still
    # fully intact, but Facts-dependent reads (architecture, blast-radius,
    # a fresh re-analysis's "reuse facts" check) need a real re-clone.
    # RepoLayout.tsx reads this to render "analysis archived -- re-analyse
    # to explore" instead of letting individual pages fail or go silently
    # empty (never an error, never a blank page -- session 16's own rule).
    facts_archived: bool


class AnalysisRunOut(BaseModel):
    id: uuid.UUID
    status: AnalysisRunStatus
    head_sha: str
    engine_version: int
    started_at: datetime
    finished_at: datetime | None


class AnalysisRunsResponse(BaseModel):
    repo_id: uuid.UUID
    runs: list[AnalysisRunOut]


class ShowcaseRepoOut(BaseModel):
    """Session 16, Part A: one card on the home page's showcase grid. ``hook``
    is a computed one-line stat string ("8,400 commits · 6 subsystems · truck
    factor 2") built server-side (app/api/repos.py::_showcase_hook) from real,
    already-persisted numbers -- never a hand-written description that could
    drift from what the pinned run actually shows."""

    id: uuid.UUID
    owner: str
    name: str
    url: str
    showcase_rank: int | None
    hook: str
    commit_count: int
    subsystem_count: int
    truck_factor: int | None
    health_score: float | None


class ShowcaseReposResponse(BaseModel):
    repos: list[ShowcaseRepoOut]
