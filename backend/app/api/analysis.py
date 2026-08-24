import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis import blast_radius
from app.analysis.identities import mask_email
from app.auth.deps import require_repo_access
from app.db.base import get_db
from app.db.models import (
    AnalysisStage,
    Contributor,
    Coupling,
    EntryPoint,
    File,
    FileExpertise,
    FileMetrics,
    Finding,
    GlossaryTerm,
    Health,
    HygieneEvent,
    ModuleCoupling,
    Repo,
    RepoPassport,
    StageStatus,
    Subsystem,
    SubsystemMember,
    TourStop,
    TruckFactor,
)
from app.db.paths import load_path_id_map, load_path_map
from app.db.runs import resolve_run_id
from app.engines.architecture import (
    cycle_severity,
    layering_violation_severity,
    layering_violations,
)
from app.engines.context import RunContext
from app.engines.coupling import confidence_hint, is_low_confidence
from app.engines.module_coupling import is_module_coupling_low_confidence
from app.engines.passport import RepoPassportData
from app.engines.risk import max_coupling_by_path
from app.engines.test_gaps import MIN_COMMITS_FOR_STALE_CLASSIFICATION
from app.schemas.analysis import (
    CITY_FILE_COLUMNS,
    ArchitectureResponse,
    BlastRadiusAffectedFileOut,
    BlastRadiusEvidenceOut,
    BlastRadiusExpertOut,
    BlastRadiusResponse,
    CityBounds,
    CityContributorOut,
    CityFileRow,
    CityFilesOut,
    CityMetricBounds,
    CityResponse,
    CitySubsystemOut,
    ContributorAliasOut,
    ContributorOut,
    ContributorsResponse,
    CouplingPairOut,
    CouplingResponse,
    CycleOut,
    DependencyEdgeOut,
    EntryPointOut,
    EntryPointsResponse,
    ExpertEntryOut,
    ExpertiseResponse,
    FindingOut,
    FindingsResponse,
    GlossaryResponse,
    GlossaryTermOut,
    HealthResponse,
    HiddenDependencyOut,
    HiddenDependencyResponse,
    HygieneEventOut,
    HygieneFileOut,
    HygieneResponse,
    KnowledgeMapContributorOut,
    KnowledgeMapEntryOut,
    KnowledgeMapResponse,
    LayeringViolationOut,
    ModuleCouplingPairOut,
    ModuleCouplingResponse,
    PassportResponse,
    RiskFileOut,
    RiskResponse,
    SubsystemMemberOut,
    SubsystemOut,
    SubsystemsResponse,
    TestGapFileOut,
    TestGapsResponse,
    TourResponse,
    TourStopOut,
    TruckFactorRemovalStepOut,
    TruckFactorResponse,
    UnreferencedFileOut,
)

KNOWLEDGE_INTERPRETATION_NOTE = (
    "Truck factor measures this project's knowledge-distribution risk -- how many "
    "contributors could stop working on it before large parts of the codebase have "
    "no remaining expert -- not any individual contributor's importance or value."
)
"""plan/RULES.md sec 11.4: the truck-factor response must always carry this
framing, not just the number. A fixed string, not derived per-repo -- the
interpretation is the same regardless of the computed value."""

GLOSSARY_LIMITATION_NOTE = (
    "This extracts the repository's own vocabulary -- terms that appear often in its "
    "class, function, and file names -- not their definitions. Compass does not know "
    "what these words mean in this domain, only that the codebase revolves around "
    "them; the linked files are where a reader would go to find out."
)
"""Session 06 Part C's honest limitation, surfaced on every /glossary response
(not just documented in the engine's own docstring) -- session 08 must reflect
this same distinction in the UI copy."""

UNREFERENCED_FILES_CAVEAT = (
    "A file can appear here even when it's genuinely used: dynamic imports, reflection, "
    "framework auto-discovery, entry points declared in configuration Compass does not parse, "
    "and (for Java) same-package references, which are all invisible to static import analysis. "
    "This list carries no severity and produces no findings -- see session 07's Part E."
)
MAX_UNREFERENCED_FILES = 25

TEST_GAP_LIMITATION_NOTE = (
    "This measures test MAINTENANCE -- whether a file's mapped tests keep changing alongside "
    "it -- never test coverage or quality. A repository with an integration-test-only strategy, "
    "or simply well-written tests that rarely need touching, will look worse here than it "
    "actually is. Mapping between a source file and its tests is best-effort (naming convention "
    "plus import edges); this is not a claim that unmapped code has no tests."
)

# Calibration is always "heuristic" until Release C wires a CorpusBaseline in
# behind the same BaselineProvider interface (master-context.md sec 9,
# decision 2) -- surfaced to the client so the UI can honestly label
# risk/health as not-yet-corpus-calibrated rather than imply a precision
# these numbers don't have yet.
CALIBRATION_LABEL = "heuristic"

router = APIRouter()


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
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> CouplingResponse | JSONResponse:
    """Ranked change-coupling pairs (master-context.md sec 5, the flagship
    feature). ``low_confidence`` mirrors CouplingEngine's small-repo
    fallback (app/engines/coupling.py) -- true whenever this repo didn't
    have enough analyzed history for a pair to reach the normal
    MIN_SHARED_REVS floor, in which case every pair's confidence is "low"."""
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
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
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
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "architecture", db)
    if pending is not None:
        return pending

    ctx = RunContext(repo_id=repo_id, run_id=resolved_run_id)
    edges = ctx.dependency_edges(db)
    graph = ctx.dependency_graph(db)
    cycles = ctx.cycles(db)
    violations = layering_violations(edges)

    # Part E: the honest replacement for dead-code detection -- non-test,
    # non-entry-point files nothing in the repo imports. No engine, no
    # table, no severity, no findings row (session 07 Known Hazard #9) --
    # "referenced" is computed directly from the edge list rather than
    # graph.in_degree(), since a file with ZERO structural edges at all
    # (neither importer nor imported) never becomes a graph node in the
    # first place and would otherwise be silently excluded.
    referenced_paths = {to_path for _, to_path in edges}
    entry_point_path_ids = set(
        db.scalars(
            select(EntryPoint.path_id).where(EntryPoint.analysis_run_id == resolved_run_id)
        ).all()
    )
    candidate_files = db.scalars(
        select(File).where(
            File.repo_id == repo_id, File.is_deleted.is_(False), File.is_test.is_(False)
        )
    ).all()
    unreferenced = sorted(
        (
            f
            for f in candidate_files
            if f.path not in referenced_paths and f.path_id not in entry_point_path_ids
        ),
        key=lambda f: f.current_loc,
        reverse=True,
    )[:MAX_UNREFERENCED_FILES]

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
        unreferenced_files=[
            UnreferencedFileOut(file_path=f.path, loc=f.current_loc) for f in unreferenced
        ],
        unreferenced_files_caveat=UNREFERENCED_FILES_CAVEAT,
    )


@router.get("/repos/{repo_id}/hidden-dependencies", response_model=HiddenDependencyResponse)
def get_hidden_dependencies(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> HiddenDependencyResponse | JSONResponse:
    """Coupled-but-not-imported pairs, ranked by coupling_degree desc -- the
    money insight (master-context.md sec 5): files that co-change without
    any import between them, recomputed fresh via app/engines/overlay.py.
    Gated on the "architecture" stage (session 04: OverlayEngine now runs
    inside that stage, after ArchEngine/EntryPointEngine -- the standalone
    "overlay" stage no longer exists, see app/jobs/stages.py)."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "architecture", db)
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
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> RiskResponse | JSONResponse:
    """Every scored file, ranked by hotspot_rank -- RiskEngine's persisted
    file_metrics rows (app/engines/risk.py), read straight rather than
    recomputed (unlike coupling/architecture, this isn't cheap enough or
    pure-graph enough to casually recompute per request, and the whole point
    of hotspot_rank is that it was decided once, deterministically, at
    analysis time). file_metrics is joined to files by path_id, not file_id
    -- see FileMetrics's docstring in app/db/models.py -- and filtered to
    this run_id, since the table holds rows from every past run."""
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

    # Session 07 (Risk v2, Part D.3): expert_count/is_orphaned_knowledge are
    # computed here, not stored -- a per-file join over `file_expertise`
    # (this run's already-persisted DOA results, session 05), cheap and
    # consistent with how /architecture recomputes cycles fresh each call.
    # /risk gates only on the "risk" stage, which runs BEFORE "knowledge" in
    # the fixed pipeline order -- if that stage hasn't finished yet for this
    # run, file_expertise is legitimately empty and every file's
    # expert_count/is_orphaned_knowledge below just defaults to 0/False,
    # the same "not computed yet" honesty every other progressive-reveal
    # field in this codebase has.
    expert_rows = db.execute(
        select(FileExpertise.path_id, FileExpertise.contributor_id, Contributor.is_stale)
        .join(Contributor, Contributor.id == FileExpertise.contributor_id)
        .where(FileExpertise.analysis_run_id == resolved_run_id, FileExpertise.is_expert.is_(True))
    ).all()
    experts_by_path: dict[int, list[bool]] = {}
    for path_id, _contributor_id, is_stale in expert_rows:
        experts_by_path.setdefault(path_id, []).append(is_stale)

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
            churn_weighted=file.churn_weighted,
            instability_score=metrics.instability_score,
            revert_cycle_count=metrics.revert_cycle_count,
            test_classification=metrics.test_classification,
            test_cochange_ratio=metrics.test_cochange_ratio,
            expert_count=len(experts_by_path.get(file.path_id, [])),
            is_orphaned_knowledge=(
                len(experts_by_path.get(file.path_id, [])) == 1 and experts_by_path[file.path_id][0]
            ),
        )
        for file, metrics in rows
    ]
    return RiskResponse(repo_id=repo_id, calibration=CALIBRATION_LABEL, files=files)


@router.get("/repos/{repo_id}/health", response_model=HealthResponse)
def get_health(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> HealthResponse | JSONResponse:
    """The single composite health score (app/engines/health.py) -- read
    straight, not recomputed, since it's already a persisted aggregate of
    the other engines' output for this analysis run. One row per run_id now
    (Phase 02), not per repo_id. Gates on "onboarding" (session 06: the
    standalone "health" stage no longer exists -- HealthEngine now runs
    inside "onboarding", after Tour/Glossary and before Passport; see
    app/jobs/stages.py)."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "onboarding", db)
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
    repo: Repo = Depends(require_repo_access),
) -> FindingsResponse | JSONResponse:
    """The single ranked findings stream (master-context.md sec 7 / sec 9
    decision 5) -- one global rank across every category (risk, architecture,
    hidden_dependency), finalized once per analysis run by
    FindingsRankEngine. Optionally filtered to a single category, but even
    filtered the ordering is still the global rank, not a re-rank within the
    filtered subset. Gated on the "rank" stage -- findings exist as soon as
    each emitting engine runs, but ``rank`` isn't final until FindingsRank
    has run last."""
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


@router.get("/repos/{repo_id}/subsystems", response_model=SubsystemsResponse)
def get_subsystems(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    include_members: bool = True,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> SubsystemsResponse | JSONResponse:
    """Subsystems for the resolved run, ranked (file_count desc, already
    decided by SubsystemEngine -- app/engines/subsystems.py), with member
    file paths and each member's PageRank centrality. ``?include_members=false``
    returns a lightweight version (labels/metrics only, no member lists) for
    callers that only need the summary. ``modularity`` isn't its own column
    (Part A's schema has none) -- it's read back from the "subsystems"
    stage's own JSONB summary, the same value SubsystemEngine returned when
    it ran, which is exactly what that summary field exists for."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "subsystems", db)
    if pending is not None:
        return pending

    stage_row = db.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == resolved_run_id, AnalysisStage.name == "subsystems"
        )
    )
    modularity = (stage_row.summary or {}).get("modularity", 0.0) if stage_row is not None else 0.0

    subsystem_rows = db.scalars(
        select(Subsystem)
        .where(Subsystem.analysis_run_id == resolved_run_id)
        .order_by(Subsystem.rank)
    ).all()

    members_by_subsystem: dict[int, list[SubsystemMemberOut]] = {}
    if include_members and subsystem_rows:
        path_map = load_path_map(repo_id, db)
        member_rows = db.execute(
            select(
                SubsystemMember.subsystem_id, SubsystemMember.path_id, SubsystemMember.centrality
            ).where(SubsystemMember.subsystem_id.in_([s.id for s in subsystem_rows]))
        ).all()
        for subsystem_id, path_id, centrality in member_rows:
            members_by_subsystem.setdefault(subsystem_id, []).append(
                SubsystemMemberOut(file_path=path_map[path_id], centrality=centrality)
            )

    subsystems = [
        SubsystemOut(
            label=s.label,
            label_source=s.label_source,
            file_count=s.file_count,
            total_loc=s.total_loc,
            internal_edges=s.internal_edges,
            external_edges=s.external_edges,
            cohesion=s.cohesion,
            rank=s.rank,
            members=members_by_subsystem.get(s.id) if include_members else None,
        )
        for s in subsystem_rows
    ]
    return SubsystemsResponse(repo_id=repo_id, modularity=modularity, subsystems=subsystems)


@router.get("/repos/{repo_id}/entry-points", response_model=EntryPointsResponse)
def get_entry_points(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> EntryPointsResponse | JSONResponse:
    """Detected entry points for the resolved run (app/engines/entrypoints.py),
    ranked (confidence desc, out-degree desc, already decided by
    EntryPointEngine). Gated on "architecture" -- EntryPointEngine runs
    inside that stage, between ArchEngine and OverlayEngine."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "architecture", db)
    if pending is not None:
        return pending

    rows = db.scalars(
        select(EntryPoint)
        .where(EntryPoint.analysis_run_id == resolved_run_id)
        .order_by(EntryPoint.rank)
    ).all()
    path_map = load_path_map(repo_id, db)
    entry_points = [
        EntryPointOut(
            file_path=path_map[r.path_id],
            kind=r.kind,
            evidence=r.evidence,
            confidence=r.confidence,
            rank=r.rank,
        )
        for r in rows
    ]
    return EntryPointsResponse(repo_id=repo_id, entry_points=entry_points)


@router.get("/repos/{repo_id}/module-coupling", response_model=ModuleCouplingResponse)
def get_module_coupling(
    repo_id: uuid.UUID,
    granularity: str = "directory",
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> ModuleCouplingResponse | JSONResponse:
    """The locked coupling formula at directory/subsystem granularity
    (app/engines/module_coupling.py), ranked by coupling_degree desc, with a
    confidence hint computed at read time via
    ``is_module_coupling_low_confidence`` -- same pattern as file-level
    ``/coupling``, reusing ``confidence_hint`` rather than duplicating it."""
    if granularity not in ("directory", "subsystem"):
        raise HTTPException(
            status_code=422, detail="granularity must be 'directory' or 'subsystem'."
        )

    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "subsystems", db)
    if pending is not None:
        return pending

    low_confidence = is_module_coupling_low_confidence(resolved_run_id, granularity, db)
    rows = db.scalars(
        select(ModuleCoupling)
        .where(
            ModuleCoupling.repo_id == repo_id,
            ModuleCoupling.analysis_run_id == resolved_run_id,
            ModuleCoupling.granularity == granularity,
        )
        .order_by(ModuleCoupling.coupling_degree.desc())
    ).all()

    pairs = [
        ModuleCouplingPairOut(
            module_a=row.module_a,
            module_b=row.module_b,
            granularity=row.granularity,
            shared_revs=row.shared_revs,
            coupling_degree=row.coupling_degree,
            avg_revs=row.avg_revs,
            confidence=confidence_hint(row.shared_revs, low_confidence),
        )
        for row in rows
    ]
    return ModuleCouplingResponse(
        repo_id=repo_id, granularity=granularity, low_confidence=low_confidence, pairs=pairs
    )


@router.get("/repos/{repo_id}/contributors", response_model=ContributorsResponse)
def get_contributors(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> ContributorsResponse | JSONResponse:
    """Every contributor identity for the resolved run (session 05,
    app/engines/expertise.py), ranked by commit_count desc (ACTIVITY, never
    a contribution score -- plan/RULES.md sec 11.3). Includes bot identities
    (``is_bot=True``) so the client can compute "N% of commits are from
    dependabot[bot]" itself; no email, canonical or aliased, is ever
    returned unmasked (plan/RULES.md sec 11.2)."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "knowledge", db)
    if pending is not None:
        return pending

    rows = db.scalars(
        select(Contributor)
        .where(Contributor.analysis_run_id == resolved_run_id)
        .order_by(Contributor.rank)
    ).all()

    contributors = [
        ContributorOut(
            id=c.id,
            canonical_name=c.canonical_name,
            canonical_email_masked=mask_email(c.canonical_email),
            aliases=[
                ContributorAliasOut(name=a["name"], email_masked=mask_email(a["email"]))
                for a in c.aliases
            ],
            commit_count=c.commit_count,
            lines_added=c.lines_added,
            lines_deleted=c.lines_deleted,
            first_commit_at=c.first_commit_at.isoformat(),
            last_commit_at=c.last_commit_at.isoformat(),
            is_bot=c.is_bot,
            active_days=c.active_days,
            is_stale=c.is_stale,
            rank=c.rank,
        )
        for c in rows
    ]
    return ContributorsResponse(repo_id=repo_id, contributors=contributors)


@router.get("/repos/{repo_id}/expertise", response_model=ExpertiseResponse)
def get_expertise(
    repo_id: uuid.UUID,
    path: str,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> ExpertiseResponse | JSONResponse:
    """The flagship endpoint (session 05, Part E): ranked experts for one
    file, by doa_normalized desc -- DOA, change count, last-touched date,
    and staleness for each. 404 (not an empty 200) when ``path`` doesn't
    resolve to a file that exists in this repo, distinct from "computed,
    genuinely no experts"."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "knowledge", db)
    if pending is not None:
        return pending

    path_id = load_path_id_map(repo_id, db).get(path)
    if path_id is None:
        raise HTTPException(status_code=404, detail="No such file in this repository.")

    rows = db.execute(
        select(FileExpertise, Contributor)
        .join(Contributor, Contributor.id == FileExpertise.contributor_id)
        .where(FileExpertise.analysis_run_id == resolved_run_id, FileExpertise.path_id == path_id)
        .order_by(FileExpertise.doa_normalized.desc())
    ).all()

    experts = [
        ExpertEntryOut(
            contributor_id=fe.contributor_id,
            canonical_name=c.canonical_name,
            canonical_email_masked=mask_email(c.canonical_email),
            doa=fe.doa,
            doa_normalized=fe.doa_normalized,
            is_expert=fe.is_expert,
            changes=fe.changes,
            last_touched_at=fe.last_touched_at.isoformat(),
            is_stale=c.is_stale,
        )
        for fe, c in rows
    ]
    return ExpertiseResponse(repo_id=repo_id, file_path=path, experts=experts)


@router.get("/repos/{repo_id}/knowledge-map", response_model=KnowledgeMapResponse)
def get_knowledge_map(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> KnowledgeMapResponse | JSONResponse:
    """Every non-deleted file's principal expert (highest doa_normalized),
    plus its subsystem -- a compact payload (ids, not repeated names) with a
    separate contributor lookup table alongside, per session 05 Part E."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "knowledge", db)
    if pending is not None:
        return pending

    files = db.scalars(
        select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
    ).all()

    best_by_path: dict[int, FileExpertise] = {}
    for fe in db.scalars(
        select(FileExpertise).where(FileExpertise.analysis_run_id == resolved_run_id)
    ).all():
        current = best_by_path.get(fe.path_id)
        if current is None or fe.doa_normalized > current.doa_normalized:
            best_by_path[fe.path_id] = fe

    subsystem_by_path: dict[int, int] = dict(
        db.execute(
            select(SubsystemMember.path_id, SubsystemMember.subsystem_id)
            .join(Subsystem, Subsystem.id == SubsystemMember.subsystem_id)
            .where(Subsystem.analysis_run_id == resolved_run_id)
        ).all()
    )

    entries = [
        KnowledgeMapEntryOut(
            file_path=f.path,
            principal_expert_contributor_id=(
                best_by_path[f.path_id].contributor_id if f.path_id in best_by_path else None
            ),
            doa_normalized=(
                best_by_path[f.path_id].doa_normalized if f.path_id in best_by_path else None
            ),
            subsystem_id=subsystem_by_path.get(f.path_id),
        )
        for f in files
    ]

    contributor_ids = {
        e.principal_expert_contributor_id
        for e in entries
        if e.principal_expert_contributor_id is not None
    }
    contributors: list[KnowledgeMapContributorOut] = []
    if contributor_ids:
        rows = db.scalars(select(Contributor).where(Contributor.id.in_(contributor_ids))).all()
        contributors = [
            KnowledgeMapContributorOut(
                id=c.id,
                canonical_name=c.canonical_name,
                canonical_email_masked=mask_email(c.canonical_email),
                is_bot=c.is_bot,
                is_stale=c.is_stale,
            )
            for c in rows
        ]

    return KnowledgeMapResponse(repo_id=repo_id, files=entries, contributors=contributors)


@router.get("/repos/{repo_id}/truck-factor", response_model=TruckFactorResponse)
def get_truck_factor(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> TruckFactorResponse | JSONResponse:
    """Truck factor for the resolved run (Avelino's greedy removal
    algorithm, app/engines/truck_factor.py) -- value, the explainable
    removal_order, and the fixed interpretation note (plan/RULES.md sec
    11.4) every response carries regardless of the computed value."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "knowledge", db)
    if pending is not None:
        return pending

    row = db.scalar(select(TruckFactor).where(TruckFactor.analysis_run_id == resolved_run_id))
    if row is None:
        # The "knowledge" stage can reach "skipped" (zero-commit repo) with
        # no truck_factor row ever written -- a legitimate empty state, not
        # an error, since _pending_response already only let us past a
        # done/skipped stage.
        return TruckFactorResponse(
            repo_id=repo_id,
            value=0,
            removal_order=[],
            total_files_considered=0,
            orphaned_file_count=0,
            note="Knowledge analysis was skipped for this run (no commit history).",
            interpretation=KNOWLEDGE_INTERPRETATION_NOTE,
        )

    removal_order = [TruckFactorRemovalStepOut(**step) for step in row.removal_order]
    return TruckFactorResponse(
        repo_id=repo_id,
        value=row.value,
        removal_order=removal_order,
        total_files_considered=row.total_files_considered,
        orphaned_file_count=row.orphaned_file_count,
        note=row.note,
        interpretation=KNOWLEDGE_INTERPRETATION_NOTE,
    )


@router.get("/repos/{repo_id}/tour", response_model=TourResponse)
def get_tour(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> TourResponse | JSONResponse:
    """The computed guided reading order (session 06, app/engines/tour.py),
    already ordered/capped by ``TourEngine`` -- read straight, not
    recomputed. ``subsystems_covered``/``of`` are derived fresh from the
    persisted stops themselves (a distinct-subsystem count over real rows),
    not read back from the "onboarding" stage's JSONB teaser -- unlike
    ``modularity`` on ``/subsystems``, this number has an underlying column
    to compute it from directly, so there is no reason to trust a teaser
    over the real data."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "onboarding", db)
    if pending is not None:
        return pending

    rows = db.scalars(
        select(TourStop)
        .where(TourStop.analysis_run_id == resolved_run_id)
        .order_by(TourStop.position)
    ).all()
    path_map = load_path_map(repo_id, db)

    stops = [
        TourStopOut(
            position=r.position,
            file_path=path_map[r.path_id],
            reason_code=r.reason_code,
            reason_detail=r.reason_detail,
            subsystem_label=(r.reason_detail or {}).get("subsystem"),
        )
        for r in rows
    ]
    total_subsystems = (
        db.scalar(
            select(func.count())
            .select_from(Subsystem)
            .where(Subsystem.analysis_run_id == resolved_run_id)
        )
        or 0
    )
    subsystems_covered = len({r.subsystem_id for r in rows if r.subsystem_id is not None})

    return TourResponse(
        repo_id=repo_id, stops=stops, subsystems_covered=subsystems_covered, of=total_subsystems
    )


@router.get("/repos/{repo_id}/glossary", response_model=GlossaryResponse)
def get_glossary(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> GlossaryResponse | JSONResponse:
    """Ranked domain-vocabulary terms (session 06, app/engines/glossary.py),
    already scored/ranked -- read straight, not recomputed. Every response
    carries the fixed ``limitation`` note (GLOSSARY_LIMITATION_NOTE above):
    this is vocabulary, not definitions."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "onboarding", db)
    if pending is not None:
        return pending

    rows = db.scalars(
        select(GlossaryTerm)
        .where(GlossaryTerm.analysis_run_id == resolved_run_id)
        .order_by(GlossaryTerm.rank)
    ).all()
    path_map = load_path_map(repo_id, db)

    terms = [
        GlossaryTermOut(
            term=r.term,
            score=r.score,
            occurrences=r.occurrences,
            subsystem_spread=r.subsystem_spread,
            defining_paths=[path_map[pid] for pid in r.defining_path_ids if pid in path_map],
            rank=r.rank,
        )
        for r in rows
    ]
    return GlossaryResponse(repo_id=repo_id, terms=terms, limitation=GLOSSARY_LIMITATION_NOTE)


@router.get("/repos/{repo_id}/passport", response_model=PassportResponse)
def get_passport(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> PassportResponse | JSONResponse:
    """The one-page computed repo passport plus the onboarding-difficulty
    score (session 06, app/engines/passport.py) -- read straight, not
    recomputed. ``calibration: "heuristic"`` labels the difficulty score
    honestly, same convention as /risk and /health."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "onboarding", db)
    if pending is not None:
        return pending

    row = db.scalar(select(RepoPassport).where(RepoPassport.analysis_run_id == resolved_run_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Passport not computed for this run.")

    return PassportResponse(
        repo_id=repo_id,
        calibration=CALIBRATION_LABEL,
        onboarding_difficulty=row.onboarding_difficulty,
        difficulty_breakdown=row.difficulty_breakdown,
        data=RepoPassportData.model_validate(row.data),
    )


@router.get("/repos/{repo_id}/blast-radius", response_model=BlastRadiusResponse)
def get_blast_radius(
    repo_id: uuid.UUID,
    path: str,
    depth: int = blast_radius.DEFAULT_BLAST_DEPTH,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> BlastRadiusResponse | JSONResponse:
    """Session 07, Part A: structural + historical blast radius for one
    file, plus the "surprising" set (coupled but never imported -- the money
    output). Pure, on-demand computation (app/analysis/blast_radius.py),
    never persisted. Gates on "coupling" (it needs this run's coupling rows;
    the dependency graph itself is Facts, unaffected by which run is
    selected -- same reasoning /architecture already documents)."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "coupling", db)
    if pending is not None:
        return pending

    depth = min(max(depth, 1), blast_radius.MAX_BLAST_DEPTH)

    path_id_map = load_path_id_map(repo_id, db)
    if path not in path_id_map:
        raise HTTPException(status_code=404, detail="No such file in this repository.")

    result = blast_radius.compute_blast_radius(db, resolved_run_id, repo_id, path, max_depth=depth)

    def _affected_out(a: blast_radius.AffectedFile) -> BlastRadiusAffectedFileOut:
        return BlastRadiusAffectedFileOut(
            file_path=a.path,
            hop_distance=a.hop_distance,
            coupling_degree=a.coupling_degree,
            risk_score=a.risk_score,
        )

    return BlastRadiusResponse(
        repo_id=repo_id,
        file_path=result.path,
        depth=result.depth,
        depth_capped=result.depth_capped,
        node_cap_engaged=result.node_cap_engaged,
        structural_affected=[_affected_out(a) for a in result.structural_affected],
        historical_affected=[_affected_out(a) for a in result.historical_affected],
        surprising_affected=[_affected_out(a) for a in result.surprising_affected],
        total_affected_count=result.total_affected_count,
        percentage_of_repo_files=result.percentage_of_repo_files,
        subsystems_touched=result.subsystems_touched,
        experts_to_review=[
            BlastRadiusExpertOut(contributor_id=e.contributor_id, canonical_name=e.canonical_name)
            for e in result.experts_to_review
        ],
        total_affected_risk_score=result.total_affected_risk_score,
        commits_touching_path=result.commits_touching_path,
        historical_evidence=[
            BlastRadiusEvidenceOut(
                affected_path=h.affected_path,
                shared_commit_count=h.shared_commit_count,
                shared_commit_percentage=h.shared_commit_percentage,
                example_shas=h.example_shas,
            )
            for h in result.historical_evidence
        ],
    )


@router.get("/repos/{repo_id}/hygiene", response_model=HygieneResponse)
def get_hygiene(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> HygieneResponse | JSONResponse:
    """Session 07, Part B: every detected commit-hygiene event for this run
    (app/engines/hygiene.py::HygieneEngine), grouped by kind, plus per-file
    instability. HygieneEngine runs inside the "risk" stage (after
    RiskEngine), so this gates on "risk", not a standalone "hygiene" stage --
    there isn't one (session 07 Part F: no new stage)."""
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "risk", db)
    if pending is not None:
        return pending

    stage_row = db.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == resolved_run_id, AnalysisStage.name == "risk"
        )
    )
    insufficient_history = bool(
        (stage_row.summary or {}).get("insufficient_history_for_oversized", False)
        if stage_row is not None
        else False
    )

    event_rows = db.scalars(
        select(HygieneEvent)
        .where(HygieneEvent.analysis_run_id == resolved_run_id)
        .order_by(HygieneEvent.occurred_at.desc())
    ).all()
    events_by_kind: dict[str, list[HygieneEventOut]] = {}
    for e in event_rows:
        events_by_kind.setdefault(e.kind, []).append(
            HygieneEventOut(
                kind=e.kind,
                commit_sha=e.commit_sha,
                occurred_at=e.occurred_at.isoformat(),
                detail=e.detail,
                severity_hint=e.severity_hint,
            )
        )

    file_rows = db.execute(
        select(File, FileMetrics)
        .join(
            FileMetrics,
            (FileMetrics.path_id == File.path_id)
            & (FileMetrics.analysis_run_id == resolved_run_id),
        )
        .where(File.repo_id == repo_id, FileMetrics.instability_score.isnot(None))
        .order_by(FileMetrics.instability_score.desc())
    ).all()
    files = [
        HygieneFileOut(
            file_path=file.path,
            instability_score=metrics.instability_score,
            revert_cycle_count=metrics.revert_cycle_count,
            oversized_commit_count=metrics.oversized_commit_count,
            fixup_commit_count=metrics.fixup_commit_count,
        )
        for file, metrics in file_rows
    ]

    return HygieneResponse(
        repo_id=repo_id,
        events_by_kind=events_by_kind,
        files=files,
        insufficient_history_for_oversized=insufficient_history,
    )


@router.get("/repos/{repo_id}/test-gaps", response_model=TestGapsResponse)
def get_test_gaps(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> TestGapsResponse | JSONResponse:
    """Session 07, Part C: test maintenance classifications
    (app/engines/test_gaps.py::TestGapEngine) -- never "coverage" or
    "untested", see TEST_GAP_LIMITATION_NOTE above, attached to every
    response. Gates on "risk" (TestGapEngine runs last in that stage, after
    RiskEngine and HygieneEngine -- no standalone stage)."""
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
        .where(File.repo_id == repo_id, FileMetrics.test_classification.isnot(None))
    ).all()
    path_map = load_path_map(repo_id, db)
    files = [
        TestGapFileOut(
            file_path=file.path,
            classification=metrics.test_classification,
            test_cochange_ratio=metrics.test_cochange_ratio,
            mapped_test_paths=[
                path_map[pid] for pid in (metrics.mapped_test_path_ids or []) if pid in path_map
            ],
        )
        for file, metrics in rows
    ]

    # test_file_ratio is purely Facts-derived (files.is_test) -- no run
    # dependency at all, unlike everything else on this response.
    test_count = (
        db.scalar(
            select(func.count())
            .select_from(File)
            .where(File.repo_id == repo_id, File.is_deleted.is_(False), File.is_test.is_(True))
        )
        or 0
    )
    source_count = (
        db.scalar(
            select(func.count())
            .select_from(File)
            .where(File.repo_id == repo_id, File.is_deleted.is_(False), File.is_test.is_(False))
        )
        or 0
    )
    test_file_ratio = test_count / source_count if source_count else 0.0

    # mean_test_cochange_ratio recomputed fresh from the persisted per-file
    # columns (like /tour's subsystems_covered) rather than trusted from the
    # engine's own stage-summary teaser -- excludes files below the same
    # commit floor TestGapEngine itself uses to avoid classifying (session
    # 07 Known Hazard #6: a low-commit file's ratio is meaningless).
    ratio_rows = db.execute(
        select(FileMetrics.test_cochange_ratio)
        .join(
            File,
            (File.path_id == FileMetrics.path_id) & (File.repo_id == repo_id),
        )
        .where(
            FileMetrics.analysis_run_id == resolved_run_id,
            FileMetrics.test_cochange_ratio.isnot(None),
            File.commit_count >= MIN_COMMITS_FOR_STALE_CLASSIFICATION,
        )
    ).all()
    ratios = [r[0] for r in ratio_rows]
    mean_ratio = sum(ratios) / len(ratios) if ratios else 0.0

    return TestGapsResponse(
        repo_id=repo_id,
        files=files,
        test_file_ratio=test_file_ratio,
        mean_test_cochange_ratio=mean_ratio,
        limitation=TEST_GAP_LIMITATION_NOTE,
    )


@router.get("/repos/{repo_id}/city", response_model=CityResponse)
def get_city(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> CityResponse | JSONResponse:
    """Session 09, Part E: the ONE backend addition this session makes --
    everything the codebase map's treemap and the 3D city need in a single
    round trip, joined from data every earlier engine in this run already
    computed. THIS ENDPOINT COMPUTES NOTHING NEW: no engine, no formula, no
    ranking decision -- if a future change needs to calculate something
    here, it belongs in an engine instead, not in this handler. Gates on
    "onboarding" (the LAST insight stage in the fixed pipeline order -- see
    app/jobs/stages.py), which guarantees "risk"/"knowledge"/"subsystems"
    have already finished for this run, so every join below reads real
    data rather than degrading to nulls the way a stage-agnostic endpoint
    would have to.

    `files` is COLUMNAR (`CITY_FILE_COLUMNS` + one `rows` tuple per file, in
    that exact column order) rather than one JSON object per file --
    measured on a synthetic ~5,000-file payload (see CLAUDE.md's "Codebase
    map" section for the measurement script): ~1.29MB as array-of-objects
    vs ~0.50MB columnar, which is why this is columnar from the start rather
    than only past some future repo-size threshold. `bounds` is computed
    once, here, from these same rows, so the treemap's colour-by-risk mode,
    the map, and the city never each derive their own min/max scale from a
    possibly-differently-filtered view of the data (Part E: "the client
    never derives its own scale").
    """
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "onboarding", db)
    if pending is not None:
        return pending

    subsystem_rows = db.scalars(
        select(Subsystem)
        .where(Subsystem.analysis_run_id == resolved_run_id)
        .order_by(Subsystem.rank)
    ).all()
    subsystems = [
        CitySubsystemOut(id=s.id, label=s.label, file_count=s.file_count, total_loc=s.total_loc)
        for s in subsystem_rows
    ]

    subsystem_by_path: dict[int, int] = dict(
        db.execute(
            select(SubsystemMember.path_id, SubsystemMember.subsystem_id)
            .join(Subsystem, Subsystem.id == SubsystemMember.subsystem_id)
            .where(Subsystem.analysis_run_id == resolved_run_id)
        ).all()
    )

    # Highest-doa_normalized expert per file -- the identical "best_by_path"
    # pattern get_knowledge_map already uses (session 05), not re-derived
    # differently here.
    best_expert_by_path: dict[int, int] = {}
    best_doa_by_path: dict[int, float] = {}
    for path_id, contributor_id, doa_normalized in db.execute(
        select(
            FileExpertise.path_id, FileExpertise.contributor_id, FileExpertise.doa_normalized
        ).where(FileExpertise.analysis_run_id == resolved_run_id)
    ).all():
        current = best_doa_by_path.get(path_id)
        if current is None or doa_normalized > current:
            best_doa_by_path[path_id] = doa_normalized
            best_expert_by_path[path_id] = contributor_id

    # LEFT joined -- RiskEngine scores every non-deleted file, but this
    # endpoint must never silently drop a file just because its
    # file_metrics row is somehow missing; the map/city need every file to
    # lay out a complete picture, not only the scored subset /risk returns.
    file_rows = db.execute(
        select(File, FileMetrics)
        .outerjoin(
            FileMetrics,
            (FileMetrics.path_id == File.path_id)
            & (FileMetrics.analysis_run_id == resolved_run_id),
        )
        .where(File.repo_id == repo_id, File.is_deleted.is_(False))
        .order_by(File.path)
    ).all()

    rows: list[CityFileRow] = [
        (
            file.path,
            subsystem_by_path.get(file.path_id),
            file.current_loc,
            file.complexity,
            metrics.risk_score if metrics is not None else None,
            metrics.risk_confidence if metrics is not None else None,
            best_expert_by_path.get(file.path_id),
            int(file.last_seen.timestamp()),
            file.commit_count,
            file.is_test,
            file.churn_weighted,
        )
        for file, metrics in file_rows
    ]

    def _bounds(values: list[float]) -> CityMetricBounds:
        if not values:
            return CityMetricBounds(min=0.0, max=0.0)
        return CityMetricBounds(min=min(values), max=max(values))

    bounds = CityBounds(
        loc=_bounds([float(r[2]) for r in rows]),
        complexity=_bounds([r[3] for r in rows]),
        risk_score=_bounds([r[4] for r in rows if r[4] is not None]),
        churn_weighted=_bounds([r[10] for r in rows]),
        commit_count=_bounds([float(r[8]) for r in rows]),
        last_modified_at=_bounds([float(r[7]) for r in rows]),
    )

    contributor_rows = db.execute(
        select(Contributor.id, Contributor.canonical_name)
        .where(Contributor.analysis_run_id == resolved_run_id)
        .order_by(Contributor.rank)
    ).all()
    contributors = [CityContributorOut(id=cid, name=name) for cid, name in contributor_rows]

    return CityResponse(
        repo_id=repo_id,
        subsystems=subsystems,
        files=CityFilesOut(columns=CITY_FILE_COLUMNS, rows=rows),
        contributors=contributors,
        bounds=bounds,
    )
