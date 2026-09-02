"""Run-vs-run compare (session 13, Part E) -- mirrors
``app/analysis/compare.py``'s ``compare_runs`` output. Kept in its own file,
matching the precedent ``app/schemas/{share,narrative}.py`` already set: a
self-contained feature gets its own schema module rather than growing the
already-large ``app/schemas/analysis.py``.
"""

import uuid

from pydantic import BaseModel


class HeadlineDeltaOut(BaseModel):
    metric: str
    label: str
    before: float | None
    after: float | None
    delta: float | None
    # True = higher is better (health, truck_factor), False = higher is
    # worse (onboarding_difficulty, high_risk_ratio, hidden_dependency_count),
    # None = no inherent direction (subsystem_count) -- what lets the
    # frontend color a "-12" green for risk and red for truck factor
    # (Part G: "the UI must know which").
    higher_is_better: bool | None


class RiskMoverOut(BaseModel):
    """Only the fields genuinely comparable ACROSS runs are included here.
    ``churn_weighted``/``complexity`` live on the Facts-layer ``files`` table,
    which reflects only the CURRENT head_sha's state (wiped and replaced on
    every re-analysis) -- there is no way to know what they were "as of"
    an older run once Facts have moved on, so this deliberately does not
    claim a before/after for them. ``risk_score``/``hotspot_rank`` (Insight,
    ``file_metrics``) and ``max_coupling_degree`` (Insight, ``coupling``) ARE
    genuinely per-run and are what's shown."""

    file_path: str
    hotspot_rank_before: int | None
    hotspot_rank_after: int | None
    rank_delta: int
    risk_score_before: float | None
    risk_score_after: float | None
    risk_score_delta: float
    max_coupling_degree_before: float
    max_coupling_degree_after: float


class CompareFindingOut(BaseModel):
    signature: str
    category: str
    severity: str
    confidence: float
    title: str
    file_path: str | None


class FindingsDiffOut(BaseModel):
    appeared: list[CompareFindingOut]
    resolved: list[CompareFindingOut]
    persisted: list[CompareFindingOut]
    appeared_total: int
    resolved_total: int
    persisted_total: int


class SubsystemChangeOut(BaseModel):
    """``kind`` is one of "appeared"/"disappeared"/"merged"/"split", detected
    by membership Jaccard similarity (>= 0.5) between a subsystem in the
    before-run and one in the after-run -- subsystem identity across runs is
    INFERRED by overlap, never tracked (there is no subsystem id stable
    across runs). A large refactor that happens to leave no >=50%-overlapping
    subsystem on either side legitimately shows as a disappearance plus an
    appearance rather than as a rename -- that is not a bug in this
    detection, it is what "identity by overlap" honestly means when the
    overlap genuinely isn't there."""

    kind: str
    label: str
    detail: str
    file_count_before: int | None
    file_count_after: int | None


class ContributorChangeOut(BaseModel):
    kind: str  # "joined" | "left" | "went_stale"
    name: str


class CouplingChangeOut(BaseModel):
    kind: str  # "appeared" | "strengthened" | "weakened" | "vanished"
    file_a_path: str
    file_b_path: str
    coupling_degree_before: float | None
    coupling_degree_after: float | None


class SecurityDiffOut(BaseModel):
    """Vulnerabilities are Insight (``analysis_run_id``-keyed) and therefore
    exactly comparable across runs. Secrets are NOT: ``secret_hits`` is
    Facts, scoped only to ``repo_id`` (a single, repo-wide history scan,
    wiped and replaced whenever ``head_sha`` changes) -- there is no
    per-run record of which secrets existed "as of" an older run, so a true
    introduced/remediated pair can't be reconstructed the way it can for
    vulnerabilities. ``secrets_introduced`` is a best-effort approximation
    (secret_hits whose OWN commit date falls between the two runs'
    ``started_at`` timestamps); ``secrets_caveat`` states this plainly rather
    than presenting the approximation as exact, and there is deliberately no
    ``secrets_remediated`` field at all -- inventing one would be a number
    with no honest basis."""

    vulnerabilities_introduced: int
    vulnerabilities_remediated: int
    secrets_introduced: int
    secrets_caveat: str


class CompareResponse(BaseModel):
    repo_id: uuid.UUID
    run_before: uuid.UUID
    run_after: uuid.UUID
    engine_version_before: int
    engine_version_after: int
    engine_version_differs: bool
    headline: list[HeadlineDeltaOut]
    risk_movers_worsened: list[RiskMoverOut]
    risk_movers_improved: list[RiskMoverOut]
    findings: FindingsDiffOut
    subsystem_changes: list[SubsystemChangeOut]
    contributor_changes: list[ContributorChangeOut]
    coupling_changes: list[CouplingChangeOut]
    security: SecurityDiffOut
