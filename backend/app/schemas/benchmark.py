"""``GET /repos/{id}/benchmark`` (session 14, Part D) -- one repository
positioned against the curated corpus (``app/baseline/corpus.py::
CorpusBaseline``), independent of whichever ``BaselineProvider`` is
currently configured to drive live risk scoring (``COMPASS_BASELINE_PROVIDER``)
-- Benchmark always compares against the corpus specifically, since that is
its whole purpose."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class BenchmarkMetricOut(BaseModel):
    metric: str
    value: float
    percentile: float
    language: str
    size_bucket: str
    widened: bool
    n_repos: int
    n_files: int


class BenchmarkResponse(BaseModel):
    repo_id: uuid.UUID
    dominant_language: str
    size_bucket: str
    metrics: list[BenchmarkMetricOut]
    corpus_note: str = (
        "Compared against a curated corpus of real, hand-reviewed repositories "
        "(see corpus_repos.yaml in the Compass repository) -- percentile calibration, "
        "not a trained model or defect prediction."
    )


__all__ = ["BenchmarkMetricOut", "BenchmarkResponse"]
