import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import Coupling, Repo
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
from app.schemas.analysis import (
    ArchitectureResponse,
    CouplingPairOut,
    CouplingResponse,
    CycleOut,
    DependencyEdgeOut,
    HiddenDependencyOut,
    HiddenDependencyResponse,
    LayeringViolationOut,
)

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
        select(Coupling).where(Coupling.repo_id == repo_id).order_by(Coupling.coupling_degree.desc())
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
            LayeringViolationOut(from_path=f, to_path=t, kind=kind, severity=layering_violation_severity(kind))
            for f, t, kind in violations
        ],
    )


@router.get("/repos/{repo_id}/hidden-dependencies", response_model=HiddenDependencyResponse)
def get_hidden_dependencies(repo_id: uuid.UUID, db: Session = Depends(get_db)) -> HiddenDependencyResponse:
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
