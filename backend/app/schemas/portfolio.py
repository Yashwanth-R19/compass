"""Portfolio + run-queue response shapes (session 14, Part A/B/E). Nested,
free-form aggregates (``pooled_distributions``, ``cross_repo_patterns``,
``growth``) are typed as plain JSON-ish dicts rather than one Pydantic model
per nested shape -- the same looseness every other JSONB-teaser field in
this codebase already carries (``AnalysisStage.summary``, ``RepoPassport.
difficulty_breakdown``); the real, load-bearing shape is documented in
``app/analysis/portfolio.py``'s own docstrings, which is the source of
truth a frontend author reads before wiring a new chart to a new key.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PortfolioAnalyzeRequest(BaseModel):
    repository_urls: list[str] = Field(min_length=1, max_length=50)


class PortfolioQueuedItemOut(BaseModel):
    repo_id: uuid.UUID
    run_id: uuid.UUID
    url: str


class PortfolioSkippedItemOut(BaseModel):
    url: str
    reason: str


class PortfolioAnalyzeResponse(BaseModel):
    queued: list[PortfolioQueuedItemOut]
    skipped: list[PortfolioSkippedItemOut]
    errors: list[PortfolioSkippedItemOut]


class QueueItemOut(BaseModel):
    run_id: uuid.UUID
    repo_id: uuid.UUID
    repo_url: str
    status: str
    position: int | None
    estimated_wait_seconds: float | None


class PortfolioQueueResponse(BaseModel):
    items: list[QueueItemOut]
    max_concurrent_runs: int


class PortfolioTotalsOut(BaseModel):
    repositories: int
    files: int
    loc: int
    commits: int
    contributors: int


class PortfolioResponse(BaseModel):
    computed_at: datetime
    repository_count: int
    totals: PortfolioTotalsOut
    language_activity_by_year: dict[str, dict[str, int]]
    pooled_distributions: dict[str, Any]
    cross_repo_patterns: dict[str, Any]
    portfolio_health: dict[str, Any]
    growth: dict[str, Any]
    # Part B / Part E: every pooled figure above is relative to the caller's
    # OWN repositories -- this note is attached at the API layer, same
    # pattern KNOWLEDGE_INTERPRETATION_NOTE/GLOSSARY_LIMITATION_NOTE already
    # use, so the frontend has a real string to render rather than having
    # to invent its own wording (and risk drifting from this one).
    pooled_distribution_label: str = (
        "Compared to your other repositories -- not a general benchmark. "
        "See the Benchmark tab for a comparison against a curated corpus of "
        "real repositories."
    )


__all__ = [
    "PortfolioAnalyzeRequest",
    "PortfolioAnalyzeResponse",
    "PortfolioQueueResponse",
    "PortfolioQueuedItemOut",
    "PortfolioResponse",
    "PortfolioSkippedItemOut",
    "PortfolioTotalsOut",
    "QueueItemOut",
]
