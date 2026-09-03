"""Pydantic schemas for ``GET /meta/{formulas,pipeline,worked-example}``
(UI rebuild session 2, Part A) -- the explainability spine's one backend
seam. See ``app/api/meta.py`` for the rule these three endpoints exist to
enforce: every value in ``FormulasResponse`` is read from the real engine /
baseline module constants at request time, never re-typed here as a
literal, so a future weight change in an engine changes this response (and
therefore the frontend) automatically.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

FormulaStatus = Literal["locked", "heuristic", "cited"]
"""Matches plan/UI_REBUILD_SESSIONS.md section 5.1 / CLAUDE.md's
locked/heuristic/cited vocabulary exactly -- see that section for what each
means. Never invented per-entry; read from each engine's own docstring."""


class FormulaConstant(BaseModel):
    name: str
    value: float | int | str
    description: str


class FormulaGroup(BaseModel):
    key: str
    label: str
    status: FormulaStatus
    formula: str
    citation: str | None = None
    constants: list[FormulaConstant]


class FormulasResponse(BaseModel):
    groups: list[FormulaGroup]
    active_baseline_provider: str


class PipelineStageOut(BaseModel):
    name: str
    kind: Literal["fact", "insight"]
    order: int
    engines: list[str]
    optional: bool
    description: str


class PipelineResponse(BaseModel):
    stages: list[PipelineStageOut]


class WorkedExampleRepoOut(BaseModel):
    id: uuid.UUID
    owner: str
    name: str
    url: str


class WorkedExampleResponse(BaseModel):
    """Every field below ``repo``/``run_id`` is nullable on its own --
    ``app/api/meta.py::get_worked_example`` reads each straight from a
    persisted row and leaves a field ``None`` when that row genuinely
    doesn't exist for this run, rather than substituting a plausible
    number. The frontend omits any stage line whose figure is ``None``
    (see plan/UI_REBUILD_SESSIONS.md section 5.2's "never invent a
    plausible number" rule, applied here to the worked example rather than
    a score explainer)."""

    repo: WorkedExampleRepoOut
    run_id: uuid.UUID
    commit_count: int | None = None
    file_count: int | None = None
    path_count: int | None = None
    symbol_count: int | None = None
    dependency_edge_count: int | None = None
    coupling_pair_count: int | None = None
    subsystem_count: int | None = None
    subsystem_labels: list[str] | None = None
    cycle_count: int | None = None
    hidden_dependency_count: int | None = None
    entry_point_count: int | None = None
    hotspot_count: int | None = None
    contributor_count: int | None = None
    truck_factor: int | None = None
    tour_stop_count: int | None = None
    glossary_term_count: int | None = None
    health_score: float | None = None
    onboarding_difficulty: float | None = None
    secret_hit_count: int | None = None
    vulnerability_count: int | None = None
    finding_count: int | None = None
