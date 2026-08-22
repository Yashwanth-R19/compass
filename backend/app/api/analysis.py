import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import (
    AnalysisStage,
    Coupling,
    File,
    FileMetrics,
    Finding,
    Health,
    Repo,
    StageStatus,
)
from app.db.paths import load_path_map
from app.db.runs import resolve_run_id
from app.engines.architecture import (
    cycle_severity,
    layering_violation_severity,
    layering_violations,
)
from app.engines.context import RunContext
from app.engines.coupling import confidence_hint, is_low_confidence
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


def _resolve_run_or_404(repo: Repo, run_id: uuid.UUID | None, db: Session) -> uuid.UUID:
    """Resolves the run an analysis endpoint should read (see
    app/db/runs.py::resolve_run_id). Raises 404 -- not 202 -- when there is
    no run to resolve to at all (a brand new repo whose ingestion job
    hasn't even created its first analysis_runs row yet); 202 is reserved
    for "a run exists but this particular stage hasn't finished computing
    for it" (see _pending_response)."""
    resolved = resolve_run_id(repo, run_id, db)
    if resolved is None:
        raise HTTPException(status_code=404, detail="No analysis run exists for this repo yet.")
    return resolved


def _pending_response(run_id: uuid.UUID, stage_name: str, db: Session) -> JSONResponse | None:
    """Gate for the ``?run_id=`` contract (Part E): returns a 202 response
    with ``{"stage": ..., "status": ...}`` if the stage that produces this
    endpoint's data hasn't reached ``done``/``skipped`` for ``run_id`` yet --
    the frontend's signal to distinguish "not computed yet" from "computed
    and genuinely empty" -- or ``None`` when the caller should proceed and
    read the real data.
    """
    stage_row = db.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == stage_name
        )
    )
    status = stage_row.status if stage_row is not None else StageStatus.pending
    if status in (StageStatus.done, StageStatus.skipped):
        return None
    return JSONResponse(status_code=202, content={"stage": stage_name, "status": status.value})


@router.get("/repos/{repo_id}/coupling", response_model=CouplingResponse)
def get_coupling(
    repo_id: uuid.UUID, run_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> CouplingResponse | JSONResponse:
    """Ranked change-coupling pairs (master-context.md sec 5, the flagship
    feature). ``low_confidence`` mirrors CouplingEngine's small-repo
    fallback (app/engines/coupling.py) -- true whenever this repo didn't
    have enough analyzed history for a pair to reach the normal
    MIN_SHARED_REVS floor, in which case every pair's confidence is "low"."""
    repo = _get_repo_or_404(repo_id, db)
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "coupling", db)
    if pending is not None:
        return pending

    low_confidence = is_low_confidence(resolved_run_id, db)
    rows = db.scalars(
        select(Coupling)
        .where(Coupling.repo_id == repo_id, Coupling.analysis_run_id == resolved_run_id)
        .order_by(Coupling.coupling_degree.desc())
    ).all()
    path_map = load_path_map(repo_id, db)

    pairs = [
        CouplingPairOut(
            file_a_path=path_map[row.path_a_id],
            file_b_path=path_map[row.path_b_id],
            coupling_degree=row.coupling_degree,
            shared_revs=row.shared_revs,
            avg_revs=row.avg_revs,
            confidence=confidence_hint(row.shared_revs, low_confidence),
        )
        for row in rows
    ]
    return CouplingResponse(repo_id=repo_id, low_confidence=low_confidence, pairs=pairs)


@router.get("/repos/{repo_id}/architecture", response_model=ArchitectureResponse)
def get_architecture(
    repo_id: uuid.UUID, run_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> ArchitectureResponse | JSONResponse:
    """The structural dependency graph: nodes/edges from `dependencies`
    (Facts -- unaffected by which run is selected), plus cycles and layering
    violations recomputed fresh from those same edges
    (app/engines/architecture.py) -- a cheap, deterministic, pure-DB
    computation, so there's no need to parse ArchEngine's persisted finding
    text back into structured data. Still gated on the "architecture" stage
    for this run, same as every other endpoint, so the frontend's
    progressive-reveal treatment is consistent across tabs even though this
    particular response doesn't itself depend on run-scoped Insight rows."""
    repo = _get_repo_or_404(repo_id, db)
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "architecture", db)
    if pending is not None:
        return pending

    ctx = RunContext(repo_id=repo_id, run_id=resolved_run_id)
    edges = ctx.dependency_edges(db)
    graph = ctx.dependency_graph(db)
    cycles = ctx.cycles(db)
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
    repo_id: uuid.UUID, run_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> HiddenDependencyResponse | JSONResponse:
    """Coupled-but-not-imported pairs, ranked by coupling_degree desc -- the
    money insight (master-context.md sec 5): files that co-change without
    any import between them, recomputed fresh via app/engines/overlay.py.
    Gated on the "overlay" stage, which is what actually needs coupling
    (run-scoped) to have finished."""
    repo = _get_repo_or_404(repo_id, db)
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "overlay", db)
    if pending is not None:
        return pending

    ctx = RunContext(repo_id=repo_id, run_id=resolved_run_id)
    hidden = ctx.hidden_dependencies(db)
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
def get_risk(
    repo_id: uuid.UUID, run_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> RiskResponse | JSONResponse:
    """Every scored file, ranked by hotspot_rank -- RiskEngine's persisted
    file_metrics rows (app/engines/risk.py), read straight rather than
    recomputed (unlike coupling/architecture, this isn't cheap enough or
    pure-graph enough to casually recompute per request, and the whole point
    of hotspot_rank is that it was decided once, deterministically, at
    analysis time). file_metrics is joined to files by path_id, not file_id
    -- see FileMetrics's docstring in app/db/models.py -- and filtered to
    this run_id, since the table holds rows from every past run."""
    repo = _get_repo_or_404(repo_id, db)
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "risk", db)
    if pending is not None:
        return pending

    rows = db.execute(
        select(File, FileMetrics)
        .join(
            FileMetrics,
            (FileMetrics.path_id == File.path_id)
            & (FileMetrics.analysis_run_id == resolved_run_id),
        )
        .where(File.repo_id == repo_id)
        .order_by(FileMetrics.hotspot_rank)
    ).all()

    max_coupling = max_coupling_by_path(repo_id, resolved_run_id, db)

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
def get_health(
    repo_id: uuid.UUID, run_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> HealthResponse | JSONResponse:
    """The single composite health score (app/engines/health.py) -- read
    straight, not recomputed, since it's already a persisted aggregate of
    the other engines' output for this analysis run. One row per run_id now
    (Phase 02), not per repo_id."""
    repo = _get_repo_or_404(repo_id, db)
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "health", db)
    if pending is not None:
        return pending

    health = db.scalar(select(Health).where(Health.analysis_run_id == resolved_run_id))
    if health is None:
        raise HTTPException(status_code=404, detail="Health not computed for this run.")

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
    repo_id: uuid.UUID,
    category: str | None = None,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> FindingsResponse | JSONResponse:
    """The single ranked findings stream (master-context.md sec 7 / sec 9
    decision 5) -- one global rank across every category (risk, architecture,
    hidden_dependency), finalized once per analysis run by
    FindingsRankEngine. Optionally filtered to a single category, but even
    filtered the ordering is still the global rank, not a re-rank within the
    filtered subset. Gated on the "rank" stage -- findings exist as soon as
    each emitting engine runs, but ``rank`` isn't final until FindingsRank
    has run last."""
    repo = _get_repo_or_404(repo_id, db)
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "rank", db)
    if pending is not None:
        return pending

    query = select(Finding).where(Finding.analysis_run_id == resolved_run_id)
    if category is not None:
        query = query.where(Finding.category == category)
    query = query.order_by(Finding.rank)

    rows = db.scalars(query).all()
    path_map = load_path_map(repo_id, db)
    findings = [
        FindingOut(
            id=f.id,
            category=f.category,
            severity=f.severity,
            confidence=f.confidence,
            file_path=path_map.get(f.path_id) if f.path_id is not None else None,
            evidence_sha=f.evidence_sha,
            title=f.title,
            detail=f.detail,
            rank=f.rank,
        )
        for f in rows
    ]
    return FindingsResponse(repo_id=repo_id, findings=findings)
