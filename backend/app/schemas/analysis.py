import uuid

from pydantic import BaseModel

from app.db.models import Severity


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


class ArchitectureResponse(BaseModel):
    repo_id: uuid.UUID
    nodes: list[str]
    edges: list[DependencyEdgeOut]
    cycles: list[CycleOut]
    layering_violations: list[LayeringViolationOut]


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
