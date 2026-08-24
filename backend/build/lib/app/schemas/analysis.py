import uuid
from typing import Any

from pydantic import BaseModel

from app.db.models import Severity
from app.engines.passport import RepoPassportData


class CouplingPairOut(BaseModel):
    file_a_path: str
    file_b_path: str
    coupling_degree: float
    shared_revs: int
    avg_revs: float
    confidence: str


class CouplingResponse(BaseModel):
    repo_id: uuid.UUID
    low_confidence: bool
    pairs: list[CouplingPairOut]


class DependencyEdgeOut(BaseModel):
    from_path: str
    to_path: str


class CycleOut(BaseModel):
    files: list[str]
    severity: Severity


class LayeringViolationOut(BaseModel):
    from_path: str
    to_path: str
    kind: str
    severity: Severity


class UnreferencedFileOut(BaseModel):
    file_path: str
    loc: int


class ArchitectureResponse(BaseModel):
    repo_id: uuid.UUID
    nodes: list[str]
    edges: list[DependencyEdgeOut]
    cycles: list[CycleOut]
    layering_violations: list[LayeringViolationOut]
    unreferenced_files: list[UnreferencedFileOut]
    unreferenced_files_caveat: str


class HiddenDependencyOut(BaseModel):
    file_a_path: str
    file_b_path: str
    coupling_degree: float
    shared_revs: int
    severity: Severity
    confidence: str


class HiddenDependencyResponse(BaseModel):
    repo_id: uuid.UUID
    pairs: list[HiddenDependencyOut]


class RiskFileOut(BaseModel):
    file_path: str
    language: str
    risk_score: float
    risk_confidence: float
    hotspot_rank: int
    churn_total: int
    complexity: float
    commit_count: int
    max_coupling_degree: float
    # Session 07 (Risk v2, Part D.3): surfaced ALONGSIDE risk_score as
    # evidence, never folded into it -- the locked formula's three terms and
    # weights are unchanged (app/engines/risk.py).
    churn_weighted: float
    instability_score: float | None
    revert_cycle_count: int | None
    test_classification: str | None
    test_cochange_ratio: float | None
    expert_count: int
    is_orphaned_knowledge: bool


class RiskResponse(BaseModel):
    repo_id: uuid.UUID
    calibration: str
    files: list[RiskFileOut]


class HealthResponse(BaseModel):
    repo_id: uuid.UUID
    calibration: str
    score: float
    high_risk_ratio: float
    cycle_count: int
    hidden_dependency_count: int
    computed_at: str


class FindingOut(BaseModel):
    id: int
    category: str
    severity: Severity
    confidence: float
    file_path: str | None
    evidence_sha: str | None
    title: str
    detail: str
    rank: int


class FindingsResponse(BaseModel):
    repo_id: uuid.UUID
    findings: list[FindingOut]


class SubsystemMemberOut(BaseModel):
    file_path: str
    centrality: float


class SubsystemOut(BaseModel):
    label: str
    label_source: str
    file_count: int
    total_loc: int
    internal_edges: int
    external_edges: int
    cohesion: float
    rank: int
    members: list[SubsystemMemberOut] | None


class SubsystemsResponse(BaseModel):
    repo_id: uuid.UUID
    modularity: float
    subsystems: list[SubsystemOut]


class EntryPointOut(BaseModel):
    file_path: str
    kind: str
    evidence: str
    confidence: float
    rank: int


class EntryPointsResponse(BaseModel):
    repo_id: uuid.UUID
    entry_points: list[EntryPointOut]


class ModuleCouplingPairOut(BaseModel):
    module_a: str
    module_b: str
    granularity: str
    shared_revs: int
    coupling_degree: float
    avg_revs: float
    confidence: str


class ModuleCouplingResponse(BaseModel):
    repo_id: uuid.UUID
    granularity: str
    low_confidence: bool
    pairs: list[ModuleCouplingPairOut]


# Session 05: contributor identities, DOA-based expertise, knowledge map,
# truck factor. Display/privacy rules (plan/RULES.md sec 11) apply to every
# one of these: no full email ever leaves this layer (see
# app/analysis/identities.py::mask_email), and every label is
# knowledge-distribution framing, never performance/ranking framing.


class ContributorAliasOut(BaseModel):
    name: str
    email_masked: str


class ContributorOut(BaseModel):
    id: int
    canonical_name: str
    canonical_email_masked: str
    aliases: list[ContributorAliasOut]
    commit_count: int
    lines_added: int
    lines_deleted: int
    first_commit_at: str
    last_commit_at: str
    is_bot: bool
    active_days: int
    is_stale: bool
    rank: int


class ContributorsResponse(BaseModel):
    repo_id: uuid.UUID
    contributors: list[ContributorOut]


class ExpertEntryOut(BaseModel):
    contributor_id: int
    canonical_name: str
    canonical_email_masked: str
    doa: float
    doa_normalized: float
    is_expert: bool
    changes: int
    last_touched_at: str
    is_stale: bool


class ExpertiseResponse(BaseModel):
    repo_id: uuid.UUID
    file_path: str
    experts: list[ExpertEntryOut]


class KnowledgeMapEntryOut(BaseModel):
    file_path: str
    principal_expert_contributor_id: int | None
    doa_normalized: float | None
    subsystem_id: int | None


class KnowledgeMapContributorOut(BaseModel):
    id: int
    canonical_name: str
    canonical_email_masked: str
    is_bot: bool
    is_stale: bool


class KnowledgeMapResponse(BaseModel):
    repo_id: uuid.UUID
    files: list[KnowledgeMapEntryOut]
    contributors: list[KnowledgeMapContributorOut]


class TruckFactorRemovalStepOut(BaseModel):
    contributor_id: int
    name: str
    files_orphaned: int
    cumulative_orphan_ratio: float


class TruckFactorResponse(BaseModel):
    repo_id: uuid.UUID
    value: int
    removal_order: list[TruckFactorRemovalStepOut]
    total_files_considered: int
    orphaned_file_count: int
    note: str | None
    interpretation: str


# Session 06: guided reading order, domain glossary, repo passport (mirrors
# app/engines/{tour,glossary,passport}.py's computed output). ``PassportResponse``
# reuses ``RepoPassportData`` (the SAME Pydantic model ``PassportEngine`` validates
# against before persisting ``repo_passport.data``) rather than re-declaring an
# equivalent nested schema a second time -- one shape, one source of truth.


class TourStopOut(BaseModel):
    position: int
    file_path: str
    reason_code: str
    reason_detail: dict[str, Any]
    subsystem_label: str | None


class TourResponse(BaseModel):
    repo_id: uuid.UUID
    stops: list[TourStopOut]
    subsystems_covered: int
    of: int


class GlossaryTermOut(BaseModel):
    term: str
    score: float
    occurrences: int
    subsystem_spread: int
    defining_paths: list[str]
    rank: int


class GlossaryResponse(BaseModel):
    repo_id: uuid.UUID
    terms: list[GlossaryTermOut]
    limitation: str


class PassportResponse(BaseModel):
    repo_id: uuid.UUID
    calibration: str
    onboarding_difficulty: float
    difficulty_breakdown: dict[str, Any]
    data: RepoPassportData


# Session 07: blast radius (mirrors app/analysis/blast_radius.py's
# dataclasses -- pure computation, never persisted, see that module's
# docstring), commit hygiene, and test gap / maintenance analysis (mirror
# app/engines/{hygiene,test_gaps}.py).


class BlastRadiusAffectedFileOut(BaseModel):
    file_path: str
    hop_distance: int | None
    coupling_degree: float | None
    risk_score: float | None


class BlastRadiusEvidenceOut(BaseModel):
    affected_path: str
    shared_commit_count: int
    shared_commit_percentage: float
    example_shas: list[str]


class BlastRadiusExpertOut(BaseModel):
    contributor_id: int
    canonical_name: str


class BlastRadiusResponse(BaseModel):
    repo_id: uuid.UUID
    file_path: str
    depth: int
    depth_capped: bool
    node_cap_engaged: bool
    structural_affected: list[BlastRadiusAffectedFileOut]
    historical_affected: list[BlastRadiusAffectedFileOut]
    surprising_affected: list[BlastRadiusAffectedFileOut]
    total_affected_count: int
    percentage_of_repo_files: float
    subsystems_touched: list[str]
    experts_to_review: list[BlastRadiusExpertOut]
    total_affected_risk_score: float
    commits_touching_path: int
    historical_evidence: list[BlastRadiusEvidenceOut]


class HygieneEventOut(BaseModel):
    kind: str
    commit_sha: str
    occurred_at: str
    detail: dict[str, Any]
    severity_hint: str


class HygieneFileOut(BaseModel):
    file_path: str
    instability_score: float | None
    revert_cycle_count: int | None
    oversized_commit_count: int | None
    fixup_commit_count: int | None


class HygieneResponse(BaseModel):
    repo_id: uuid.UUID
    events_by_kind: dict[str, list[HygieneEventOut]]
    files: list[HygieneFileOut]
    insufficient_history_for_oversized: bool


class TestGapFileOut(BaseModel):
    file_path: str
    classification: str
    test_cochange_ratio: float | None
    mapped_test_paths: list[str]


class TestGapsResponse(BaseModel):
    repo_id: uuid.UUID
    files: list[TestGapFileOut]
    test_file_ratio: float
    mean_test_cochange_ratio: float
    limitation: str
