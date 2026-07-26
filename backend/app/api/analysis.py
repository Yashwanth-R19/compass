import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import Coupling, File, FileMetrics, Finding, Health, Repo
from app.engines.architecture import (
    build_graph,
    cycle_severity,
    find_cycles,
    layering_violation_severity,
    layering_violations,
    load_edges,
)
from app.engines.coupling import confidence_hint, is_low_confidence
from app.engines.overlay import compute_hidden_dependencies
from app.engines.risk import max_coupling_by_path
from app.schemas.analysis import (
    ArchitectureResponse,
    CouplingPairOut,
    CouplingResponse,
    CycleOut,
    DependencyEdgeOut,
    FindingOut,
    FindingsResponse,
    HealthResponse,
    HiddenDependencyOut,
    HiddenDependencyResponse,
    LayeringViolationOut,
    RiskFileOut,
    RiskResponse,
)

# Calibration is always "heuristic" until Release C wires a CorpusBaseline in
# behind the same BaselineProvider interface (master-context.md sec 9,
# decision 2) -- surfaced to the client so the UI can honestly label
# risk/health as not-yet-corpus-calibrated rather than imply a precision
# these numbers don't have yet.
CALIBRATION_LABEL = "heuristic"

router = APIRouter()


def _get_repo_or_404(repo_id: uuid.UUID, db: Session) -> Repo:
    repo = db.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repo not found.")
    return repo


@router.get("/repos/{repo_id}/coupling", response_model=CouplingResponse)
def get_coupling(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> CouplingResponse:
    """Ranked change-coupling pairs (master-context.md sec 5, the flagship
    feature). ``low_confidence`` mirrors CouplingEngine's small-repo
    fallback (app/engines/coupling.py) -- true whenever this repo didn't
    have enough analyzed history for a pair to reach the normal
    MIN_SHARED_REVS floor, in which case every pair's confidence is "low"."""
    _get_repo_or_404(repo_id, db)

    low_confidence = is_low_confidence(repo_id, db)
    rows = db.scalars(
        select(Coupling)
        .where(Coupling.repo_id == repo_id)
        .order_by(Coupling.coupling_degree.desc())
    ).all()

    pairs = [
        CouplingPairOut(
            file_a_path=row.file_a_path,
            file_b_path=row.file_b_path,
            coupling_degree=row.coupling_degree,
            shared_revs=row.shared_revs,
            avg_revs=row.avg_revs,
            confidence=confidence_hint(row.shared_revs, low_confidence),
        )
        for row in rows
    ]
    return CouplingResponse(repo_id=repo_id, low_confidence=low_confidence, pairs=pairs)


@router.get("/repos/{repo_id}/architecture", response_model=ArchitectureResponse)
def get_architecture(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> ArchitectureResponse:
    """The structural dependency graph: nodes/edges from `dependencies`,
    plus cycles and layering violations recomputed fresh from those same
    edges (app/engines/architecture.py) -- a cheap, deterministic, pure-DB
    computation, so there's no need to parse ArchEngine's persisted finding
    text back into structured data."""
    _get_repo_or_404(repo_id, db)

    edges = load_edges(repo_id, db)
    graph = build_graph(edges)
    cycles = find_cycles(graph)
    violations = layering_violations(edges)

    return ArchitectureResponse(
        repo_id=repo_id,
        nodes=sorted(graph.nodes()),
        edges=[DependencyEdgeOut(from_path=f, to_path=t) for f, t in edges],
        cycles=[CycleOut(files=cycle, severity=cycle_severity(len(cycle))) for cycle in cycles],
        layering_violations=[
            LayeringViolationOut(
                from_path=f, to_path=t, kind=kind, severity=layering_violation_severity(kind)
            )
            for f, t, kind in violations
        ],
    )


@router.get("/repos/{repo_id}/hidden-dependencies", response_model=HiddenDependencyResponse)
def get_hidden_dependencies(
    repo_id: uuid.UUID, db: Session = Depends(get_db)
) -> HiddenDependencyResponse:
    """Coupled-but-not-imported pairs, ranked by coupling_degree desc -- the
    money insight (master-context.md sec 5): files that co-change without
    any import between them, recomputed fresh via app/engines/overlay.py."""
    _get_repo_or_404(repo_id, db)

    hidden = compute_hidden_dependencies(repo_id, db)
    pairs = [
        HiddenDependencyOut(
            file_a_path=h["file_a_path"],
            file_b_path=h["file_b_path"],
            coupling_degree=h["coupling_degree"],
            shared_revs=h["shared_revs"],
            severity=h["severity"],
            confidence=h["confidence_hint"],
        )
        for h in hidden
    ]
    return HiddenDependencyResponse(repo_id=repo_id, pairs=pairs)


@router.get("/repos/{repo_id}/risk", response_model=RiskResponse)
def get_risk(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> RiskResponse:
    """Every scored file, ranked by hotspot_rank -- RiskEngine's persisted
    file_metrics rows (app/engines/risk.py), read straight rather than
    recomputed (unlike coupling/architecture, this isn't cheap enough or
    pure-graph enough to casually recompute per request, and the whole point
    of hotspot_rank is that it was decided once, deterministically, at
    analysis time)."""
    _get_repo_or_404(repo_id, db)

    rows = db.execute(
        select(File, FileMetrics)
        .join(FileMetrics, FileMetrics.file_id == File.id)
        .where(File.repo_id == repo_id)
        .order_by(FileMetrics.hotspot_rank)
    ).all()

    max_coupling = max_coupling_by_path(repo_id, db)

    files = [
        RiskFileOut(
            file_path=file.path,
            language=file.language,
            risk_score=metrics.risk_score,
            risk_confidence=metrics.risk_confidence,
            hotspot_rank=metrics.hotspot_rank,
            churn_total=file.churn_total,
            complexity=file.complexity,
            commit_count=file.commit_count,
            max_coupling_degree=max_coupling.get(file.path, 0.0),
        )
        for file, metrics in rows
    ]
    return RiskResponse(repo_id=repo_id, calibration=CALIBRATION_LABEL, files=files)


@router.get("/repos/{repo_id}/health", response_model=HealthResponse)
def get_health(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> HealthResponse:
    """The single composite health score (app/engines/health.py) -- read
    straight, not recomputed, since it's already a persisted aggregate of
    the other engines' output for this analysis run."""
    _get_repo_or_404(repo_id, db)

    health = db.scalar(select(Health).where(Health.repo_id == repo_id))
    if health is None:
        raise HTTPException(status_code=404, detail="Health not computed for this repo yet.")

    return HealthResponse(
        repo_id=repo_id,
        calibration=CALIBRATION_LABEL,
        score=health.score,
        high_risk_ratio=health.high_risk_ratio,
        cycle_count=health.cycle_count,
        hidden_dependency_count=health.hidden_dependency_count,
        computed_at=health.computed_at.isoformat(),
    )


@router.get("/repos/{repo_id}/findings", response_model=FindingsResponse)
def get_findings(
    repo_id: uuid.UUID, category: str | None = None, db: Session = Depends(get_db)
) -> FindingsResponse:
    """The single ranked findings stream (master-context.md sec 7 / sec 9
    decision 5) -- one global rank across every category (risk, architecture,
    hidden_dependency), finalized once per analysis run by
    FindingsRankEngine. Optionally filtered to a single category, but even
    filtered the ordering is still the global rank, not a re-rank within the
    filtered subset."""
    _get_repo_or_404(repo_id, db)

    query = select(Finding).where(Finding.repo_id == repo_id)
    if category is not None:
        query = query.where(Finding.category == category)
    query = query.order_by(Finding.rank)

    rows = db.scalars(query).all()
    findings = [
        FindingOut(
            id=f.id,
            category=f.category,
            severity=f.severity,
            confidence=f.confidence,
            file_path=f.file_path,
            evidence_sha=f.evidence_sha,
            title=f.title,
            detail=f.detail,
            rank=f.rank,
        )
        for f in rows
    ]
    return FindingsResponse(repo_id=repo_id, findings=findings)
