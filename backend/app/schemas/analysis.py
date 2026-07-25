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
    id: uuid.UUID
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
