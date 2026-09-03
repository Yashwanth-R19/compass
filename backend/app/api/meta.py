"""``GET /meta/{formulas,pipeline,worked-example}`` (UI rebuild session 2,
Part A) -- three small, public, read-only endpoints that make Compass's own
pipeline and formulas traceable from the frontend without the frontend ever
hardcoding a weight, threshold, or stage list of its own.

**The rule this whole module exists to enforce**: every constant in
``get_formulas`` is imported directly from the engine/baseline module that
actually uses it, never re-typed as a Python literal here. If a future
session changes ``RiskEngine``'s weights, this endpoint's response changes
with it -- there is no second copy to keep in sync. Similarly,
``get_pipeline`` reads its stage list, order and engine names straight off
``app/jobs/stages.py``'s ``ALL_STAGES`` tuple (the single source of truth
the runner itself drives off) rather than a hand-maintained duplicate; only
each stage's plain-English `description` is hand-written (transcribed from
CLAUDE.md's own stage documentation, per this session's own instructions).

All three routes are public (no auth) -- they describe how Compass computes,
not any one repository's private data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.baseline.corpus import MIN_CORPUS_REPOS_PER_CELL
from app.config import settings
from app.db.base import get_db
from app.db.models import (
    Commit,
    Contributor,
    Coupling,
    Dependency,
    EntryPoint,
    File,
    Finding,
    GlossaryTerm,
    Health,
    RepoPassport,
    RepoPath,
    SecretHit,
    Subsystem,
    Symbol,
    TourStop,
    TruckFactor,
    Vulnerability,
)
from app.db.models import Repo as RepoModel
from app.engines import coupling as coupling_engine_module
from app.engines import expertise, glossary, health, hygiene, module_coupling, passport
from app.engines import risk as risk_engine_module
from app.engines import subsystems as subsystems_module
from app.engines import test_gaps as test_gaps_module
from app.engines import truck_factor as truck_factor_module
from app.engines.findings import SEVERITY_WEIGHT
from app.jobs.stages import ALL_STAGES, FACT_STAGES
from app.schemas.meta import (
    FormulaConstant,
    FormulaGroup,
    FormulasResponse,
    PipelineResponse,
    PipelineStageOut,
    WorkedExampleRepoOut,
    WorkedExampleResponse,
)

router = APIRouter(prefix="/meta")

DOA_CITATION = (
    "Fernández-Ramil, Izquierdo-Cortázar & Mens; as used by Avelino, Passos, Hora & Valente, "
    '"A Novel Approach for Estimating Truck Factors" (ICPC 2016)'
)


def _c(name: str, value: float | int | str, description: str) -> FormulaConstant:
    return FormulaConstant(name=name, value=value, description=description)


@router.get("/formulas", response_model=FormulasResponse)
def get_formulas() -> FormulasResponse:
    groups = [
        FormulaGroup(
            key="risk",
            label="Risk score",
            status="locked",
            formula=(
                "risk_score = 0.60 x norm(churn_weighted x complexity) "
                "+ 0.25 x norm(max coupling_degree) + 0.15 x norm(commit_count)"
            ),
            constants=[
                _c(
                    "churn_complexity_weight",
                    risk_engine_module.RISK_CHURN_COMPLEXITY_WEIGHT,
                    "Weight on the normalized churn x complexity term -- the original, "
                    "most-validated hotspot signal, so it carries the majority weight.",
                ),
                _c(
                    "coupling_weight",
                    risk_engine_module.RISK_COUPLING_WEIGHT,
                    "Weight on the normalized max coupling_degree term.",
                ),
                _c(
                    "commit_count_weight",
                    risk_engine_module.RISK_COMMIT_COUNT_WEIGHT,
                    "Weight on the normalized commit_count term -- a mild activity/maturity "
                    "tiebreaker.",
                ),
                _c(
                    "risk_confidence_commit_divisor",
                    risk_engine_module.RISK_CONFIDENCE_COMMIT_DIVISOR,
                    "risk_confidence = min(1, commit_count / this) -- independent of "
                    "risk_score, never folded into the weighted sum above.",
                ),
                _c(
                    "high_risk_severity",
                    risk_engine_module.RISK_HIGH_SEVERITY,
                    "risk_score at or above this value is a HIGH severity finding.",
                ),
                _c(
                    "med_risk_severity",
                    risk_engine_module.RISK_MED_SEVERITY,
                    "risk_score at or above this value (and below the high threshold) is a "
                    "MEDIUM severity finding.",
                ),
                _c(
                    "max_risk_findings",
                    risk_engine_module.MAX_RISK_FINDINGS,
                    "Only the top-N hotspots by risk_score become findings; every scored "
                    "file still gets a persisted risk_score regardless.",
                ),
            ],
        ),
        FormulaGroup(
            key="coupling",
            label="Change coupling",
            status="locked",
            formula="coupling_degree(A, B) = shared_revs / min(revs(A), revs(B))",
            constants=[
                _c(
                    "max_changeset_size",
                    coupling_engine_module.MAX_CHANGESET_SIZE,
                    "A commit touching more files than this is dropped from the coupling "
                    "scan entirely (a repo-wide reformat is not real co-change signal).",
                ),
                _c(
                    "min_shared_revs",
                    coupling_engine_module.MIN_SHARED_REVS,
                    "A file pair needs at least this many shared revisions to be kept.",
                ),
                _c(
                    "min_coupling_degree",
                    coupling_engine_module.MIN_COUPLING_DEGREE,
                    "A file pair needs coupling_degree at or above this value to be kept.",
                ),
                _c(
                    "fallback_min_shared_revs",
                    coupling_engine_module.FALLBACK_MIN_SHARED_REVS,
                    "On a small repository where the normal floor would keep zero pairs, "
                    "the shared-revisions floor is lowered to this value instead, and the "
                    "run is marked low-confidence.",
                ),
            ],
        ),
        FormulaGroup(
            key="module_coupling",
            label="Module-level coupling",
            status="locked",
            formula=(
                "The identical locked coupling_degree formula, computed directly from "
                "directory- or subsystem-grain commit changesets -- never aggregated from "
                "file-pair values."
            ),
            constants=[
                _c(
                    "max_dir_depth",
                    module_coupling.MAX_DIR_DEPTH,
                    "A file's directory module is its parent path truncated to this many "
                    "leading segments.",
                ),
                _c(
                    "max_module_changeset",
                    module_coupling.MAX_MODULE_CHANGESET,
                    "A commit touching more distinct MODULES than this is dropped -- "
                    "deliberately smaller than the file-level cap.",
                ),
                _c(
                    "min_shared_revs_module",
                    module_coupling.MIN_SHARED_REVS_MODULE,
                    "Same floor as file-level coupling, applied at module grain.",
                ),
                _c(
                    "min_coupling_degree_module",
                    module_coupling.MIN_COUPLING_DEGREE_MODULE,
                    "Same threshold as file-level coupling, applied at module grain.",
                ),
            ],
        ),
        FormulaGroup(
            key="health",
            label="Health score",
            status="heuristic",
            formula=(
                "health = 100 - risk penalty (cap 40) - 6 per cycle (cap 30) "
                "- 3 per hidden-dependency pair (cap 30)"
            ),
            constants=[
                _c(
                    "risk_penalty_weight",
                    health.RISK_PENALTY_WEIGHT,
                    "Maximum points deducted for the proportion of high-risk files.",
                ),
                _c(
                    "cycle_penalty_per_cycle",
                    health.CYCLE_PENALTY_PER_CYCLE,
                    "Points deducted per detected circular dependency.",
                ),
                _c("cycle_penalty_cap", health.CYCLE_PENALTY_CAP, "Cap on the cycle penalty."),
                _c(
                    "hidden_dep_penalty_per_pair",
                    health.HIDDEN_DEP_PENALTY_PER_PAIR,
                    "Points deducted per hidden-dependency pair.",
                ),
                _c(
                    "hidden_dep_penalty_cap",
                    health.HIDDEN_DEP_PENALTY_CAP,
                    "Cap on the hidden-dependency penalty.",
                ),
                _c(
                    "high_risk_threshold",
                    health.HIGH_RISK_THRESHOLD,
                    "A file's risk_score at or above this value counts toward "
                    "high_risk_ratio -- a distinct number from RiskEngine's own "
                    "0.70 finding-severity threshold.",
                ),
            ],
        ),
        FormulaGroup(
            key="onboarding_difficulty",
            label="Onboarding difficulty",
            status="heuristic",
            formula=(
                "difficulty = 100 x (0.25 x norm(subsystem_count) "
                "+ 0.20 x norm(median_file_complexity) + 0.20 x (1 - doc_coverage) "
                "+ 0.20 x (1 - min(1, truck_factor / 4)) + 0.15 x norm(max_dependency_depth))"
            ),
            constants=[
                _c(
                    "subsystem_count_weight",
                    passport.DIFFICULTY_SUBSYSTEM_COUNT_WEIGHT,
                    "Weight on the normalized subsystem count.",
                ),
                _c(
                    "median_complexity_weight",
                    passport.DIFFICULTY_MEDIAN_COMPLEXITY_WEIGHT,
                    "Weight on the normalized median file complexity.",
                ),
                _c(
                    "doc_coverage_weight",
                    passport.DIFFICULTY_DOC_COVERAGE_WEIGHT,
                    "Weight on (1 - doc_coverage) -- already bounded to [0,1] by its own "
                    "arithmetic, so it is not passed through norm().",
                ),
                _c(
                    "truck_factor_weight",
                    passport.DIFFICULTY_TRUCK_FACTOR_WEIGHT,
                    "Weight on (1 - min(1, truck_factor / 4)) -- also not passed through "
                    "norm() for the same reason.",
                ),
                _c(
                    "max_dependency_depth_weight",
                    passport.DIFFICULTY_MAX_DEP_DEPTH_WEIGHT,
                    "Weight on the normalized maximum dependency-graph depth from any "
                    "entry point.",
                ),
                _c(
                    "dormant_after_days",
                    passport.DORMANT_AFTER_DAYS,
                    "No commits within this many days of the run's own start time reads as "
                    "a dormant repository.",
                ),
            ],
        ),
        FormulaGroup(
            key="expertise",
            label="Degree of authorship",
            status="cited",
            citation=DOA_CITATION,
            formula="DOA(d, f) = 3.293 + 1.098 x FA + 0.164 x DL - 0.321 x ln(1 + AC)",
            constants=[
                _c("doa_base", expertise.DOA_BASE, "The published base constant."),
                _c(
                    "doa_fa_weight",
                    expertise.DOA_FA_WEIGHT,
                    "Weight on FA -- 1 if this developer authored the file's first commit.",
                ),
                _c(
                    "doa_dl_weight",
                    expertise.DOA_DL_WEIGHT,
                    "Weight on DL -- this developer's own change count on the file.",
                ),
                _c(
                    "doa_ac_weight",
                    expertise.DOA_AC_WEIGHT,
                    "Weight on ln(1 + AC), subtracted -- AC is every OTHER developer's "
                    "change count on the file.",
                ),
                _c(
                    "expert_doa_normalized_threshold",
                    expertise.EXPERT_DOA_NORMALIZED_THRESHOLD,
                    "A developer must reach at least this fraction of the file's own "
                    "maximum DOA to count as an expert.",
                ),
                _c(
                    "expert_doa_absolute_threshold",
                    expertise.EXPERT_DOA_ABSOLUTE_THRESHOLD,
                    "An expert must also clear this absolute DOA floor, independent of the "
                    "normalized threshold.",
                ),
                _c(
                    "max_experts_per_file",
                    expertise.MAX_EXPERTS_PER_FILE,
                    "Only the top-N contributors per file are persisted, ranked before "
                    "this truncation, never after.",
                ),
                _c(
                    "stale_after_days",
                    expertise.STALE_AFTER_DAYS,
                    "A contributor is stale once this many days have passed since their "
                    "last commit, measured against the repository's own last commit, "
                    "never wall-clock time.",
                ),
            ],
        ),
        FormulaGroup(
            key="truck_factor",
            label="Truck factor",
            status="cited",
            citation=DOA_CITATION,
            formula=(
                "Avelino greedy removal: repeatedly remove the non-bot contributor who is "
                "expert for the most still-covered files, until more than this fraction of "
                "considered files have lost every expert. The count removed is the truck "
                "factor."
            ),
            constants=[
                _c(
                    "orphan_stop_ratio",
                    truck_factor_module.ORPHAN_STOP_RATIO,
                    "Strict greater-than -- reaching exactly this fraction does not yet "
                    "stop the removal loop.",
                ),
            ],
        ),
        FormulaGroup(
            key="hygiene",
            label="Commit hygiene",
            status="heuristic",
            formula="instability_score = norm(oversized_count + fixup_count + 2 x revert_count)",
            constants=[
                _c(
                    "instability_revert_weight",
                    hygiene.INSTABILITY_REVERT_WEIGHT,
                    "A revert cycle counts double -- undoing a change entirely is a "
                    "stronger instability signal than one oversized commit.",
                ),
                _c(
                    "fixup_window_minutes",
                    hygiene.FIXUP_WINDOW_MINUTES,
                    "Consecutive same-author commits within this many minutes of each "
                    "other, touching an overlapping file, may form a fixup-churn cluster.",
                ),
                _c(
                    "fixup_min_consecutive",
                    hygiene.FIXUP_MIN_CONSECUTIVE,
                    "Minimum consecutive commits in a cluster for it to be reported.",
                ),
                _c(
                    "risky_min_subsystems",
                    hygiene.RISKY_MIN_SUBSYSTEMS,
                    "A commit touching at least this many distinct subsystems scores a "
                    "risky-commit point.",
                ),
                _c(
                    "risky_churn_quintile_fraction",
                    hygiene.RISKY_CHURN_QUINTILE_FRACTION,
                    "A commit in this repository's own top churn quintile scores a "
                    "risky-commit point.",
                ),
                _c(
                    "risky_min_message_length",
                    hygiene.RISKY_MIN_MESSAGE_LENGTH,
                    "A commit message shorter than this many characters scores a "
                    "risky-commit point.",
                ),
                _c(
                    "risky_min_score",
                    hygiene.RISKY_MIN_SCORE,
                    "A commit is reported as risky once it scores at least this many of "
                    "the four conditions.",
                ),
                _c(
                    "min_commits_for_percentile",
                    hygiene.MIN_COMMITS_FOR_PERCENTILE,
                    "Below this many total commits, oversized-commit detection is skipped "
                    "entirely -- a percentile over a handful of points is noise.",
                ),
            ],
        ),
        FormulaGroup(
            key="test_gaps",
            label="Test maintenance",
            status="heuristic",
            formula=(
                "stale_test iff a mapped test exists, test_cochange_ratio <= threshold, "
                "and the file has enough commit history to classify"
            ),
            constants=[
                _c(
                    "stale_test_ratio_threshold",
                    test_gaps_module.STALE_TEST_RATIO_THRESHOLD,
                    "test_cochange_ratio at or below this value classifies as stale_test.",
                ),
                _c(
                    "min_commits_for_stale_classification",
                    test_gaps_module.MIN_COMMITS_FOR_STALE_CLASSIFICATION,
                    "A file needs at least this many commits before it can be classified "
                    "stale_test at all -- otherwise it is left as tracked, benefit of the "
                    "doubt.",
                ),
            ],
        ),
        FormulaGroup(
            key="findings_rank",
            label="Findings ranking",
            status="locked",
            formula="impact_score = SEVERITY_WEIGHT[severity] x 10 + confidence",
            constants=[
                _c(
                    "severity_weight_high",
                    _severity_weight_by_name("high"),
                    "Weight for a high-severity finding -- severity is always the primary "
                    "sort key, confidence only breaks ties within the same band.",
                ),
                _c(
                    "severity_weight_med",
                    _severity_weight_by_name("med"),
                    "Weight for a medium-severity finding.",
                ),
                _c(
                    "severity_weight_low",
                    _severity_weight_by_name("low"),
                    "Weight for a low-severity finding.",
                ),
            ],
        ),
        FormulaGroup(
            key="subsystems",
            label="Subsystem discovery",
            status="heuristic",
            formula=(
                "Deterministic Louvain community detection over an undirected graph "
                "weighted by structural import edges and this run's own coupling pairs."
            ),
            constants=[
                _c(
                    "louvain_seed",
                    subsystems_module.LOUVAIN_SEED,
                    "A fixed random seed -- determinism is a core product claim, and "
                    "Louvain's local-move phase is internally randomized without one.",
                ),
                _c(
                    "louvain_resolution",
                    subsystems_module.LOUVAIN_RESOLUTION,
                    "The Louvain resolution parameter.",
                ),
                _c(
                    "min_subsystem_size",
                    subsystems_module.MIN_SUBSYSTEM_SIZE,
                    "A community smaller than this merges into whichever other community "
                    "it has the most edge weight to.",
                ),
                _c(
                    "max_subsystems",
                    subsystems_module.MAX_SUBSYSTEMS,
                    "At most this many subsystems are kept -- the rest fold into a single "
                    '"Other" bucket.',
                ),
                _c(
                    "w_struct",
                    subsystems_module.W_STRUCT,
                    "Edge weight contributed by one structural import edge.",
                ),
                _c(
                    "w_couple",
                    subsystems_module.W_COUPLE,
                    "Edge weight multiplier applied to this run's own coupling_degree -- "
                    "weighted higher than a single import, since a persistent co-change "
                    "relationship is stronger evidence.",
                ),
            ],
        ),
        FormulaGroup(
            key="glossary",
            label="Domain glossary",
            status="heuristic",
            formula=("score = log(1 + occurrences) x " "(1 + subsystem_spread / total_subsystems)"),
            constants=[
                _c(
                    "min_token_length",
                    glossary.MIN_TOKEN_LENGTH,
                    "A tokenized identifier or file-stem fragment shorter than this many "
                    "characters is dropped as noise before scoring.",
                ),
                _c(
                    "max_glossary_terms",
                    glossary.MAX_GLOSSARY_TERMS,
                    "Only the top-N ranked terms by score are kept.",
                ),
                _c(
                    "max_defining_paths_per_term",
                    glossary.MAX_DEFINING_PATHS_PER_TERM,
                    "Up to this many defining files are linked per term, preferring "
                    "exported class/interface/type symbols over a term that only "
                    "appears inside a function body.",
                ),
            ],
        ),
        FormulaGroup(
            key="baseline",
            label="Corpus calibration",
            status="heuristic",
            formula=(
                "A (metric, language, size_bucket) cell backed by fewer than this many "
                "contributing repositories widens to a coarser cell before falling back "
                "to the per-repository heuristic normalizer."
            ),
            constants=[
                _c(
                    "min_corpus_repos_per_cell",
                    MIN_CORPUS_REPOS_PER_CELL,
                    "The corpus cell-size gate.",
                ),
            ],
        ),
    ]
    return FormulasResponse(
        groups=groups, active_baseline_provider=settings.COMPASS_BASELINE_PROVIDER
    )


def _severity_weight_by_name(name: str) -> int:
    for severity, weight in SEVERITY_WEIGHT.items():
        if severity.value == name:
            return weight
    raise KeyError(name)


# ---- GET /meta/pipeline ----------------------------------------------------

_FACT_STAGE_ENGINES: dict[str, list[str]] = {
    "clone": ["clone_repo"],
    "mine": ["mine_repo"],
    "structure": ["extract_structural_edges", "extract_manifests", "extract_declared_dependencies"],
    "persist_facts": ["persist_facts"],
    "secrets": ["scan_history"],
}
"""FACT_STAGES carries no `callables` (app/jobs/stages.py's own docstring:
each fact stage's local state doesn't fit the uniform Engine signature, so
`run_ingestion_job` runs their bodies inline) -- there is nothing to
introspect for these five, so their function names are transcribed by hand
from CLAUDE.md's own pipeline documentation, same discipline as the
hand-written `description` field below."""

_STAGE_DESCRIPTIONS: dict[str, str] = {
    "clone": "Clones the repository to a temporary directory (single-branch, full history).",
    "mine": (
        "Streams the full commit log into structured commit and file-change records -- a "
        "pure function with no database access."
    ),
    "structure": (
        "Walks the checked-out tree with tree-sitter-based language analyzers to extract "
        "import edges and symbol declarations, and separately parses manifest and "
        "dependency-declaration files (package.json, pyproject.toml, package-lock.json, "
        "pom.xml, and more)."
    ),
    "persist_facts": (
        "Replaces the repository's commits, files, dependencies, symbols, manifests and "
        "secret-scan Facts tables with this run's freshly mined data -- the one exception, "
        "repo_paths, is append-only and never wiped."
    ),
    "secrets": (
        "Scans the full git history diff for credential-shaped secrets, using the "
        "path ids persist_facts just interned."
    ),
    "coupling": (
        "Computes the locked change-coupling formula over every pair of files that "
        "changed together across the repository's history."
    ),
    "subsystems": (
        "Partitions the dependency-and-coupling graph into named subsystems via "
        "deterministic Louvain community detection, then computes the same locked "
        "coupling formula at directory and subsystem granularity."
    ),
    "architecture": (
        "Builds the import dependency graph, finds circular dependencies and layering "
        "violations, detects entry points, and joins coupling against dependencies to "
        "surface hidden change-coupling with no structural edge."
    ),
    "risk": (
        "Computes the locked calibrated risk score per file, then adds commit-hygiene "
        "signals (oversized commits, fixup churn, risky commits) and test-maintenance "
        "mapping on top of it."
    ),
    "knowledge": (
        "Computes Degree-of-Authorship per file per contributor and derives the "
        "repository's truck factor via greedy expert removal."
    ),
    "onboarding": (
        "Builds a guided reading order, extracts a domain vocabulary glossary, computes "
        "historical snapshots for the evolution scrubber, composes the overall health "
        "score, and assembles the one-page repo passport."
    ),
    "security": (
        "Looks up each declared dependency against the OSV.dev vulnerability database, "
        "then emits findings for detected secrets and vulnerabilities."
    ),
    "rank": (
        "Applies one global, cross-category ranking to every finding this run produced, "
        "so the findings stream is a single ordered list rather than several "
        "per-category ones stapled together."
    ),
}

_WRAPPED_ENGINE_NAMES: dict[str, str] = {
    "_run_risk_engine": "RiskEngine",
    "_run_hygiene_engine": "HygieneEngine",
    "_run_passport_engine": "PassportEngine",
}
"""Three of INSIGHT_STAGES's callables are plain module-level functions
(app/jobs/stages.py), not bound `SomeEngine().run` methods, because they
construct their engine per-call with an injected BaselineProvider that needs
a live session (session 14) -- see that module's own docstring. This maps
each wrapper back to the engine class it actually runs, so the pipeline
response still names the real engine rather than a private helper
function."""


def _engine_name(callable_: Any) -> str:
    bound_self = getattr(callable_, "__self__", None)
    if bound_self is not None:
        return type(bound_self).__name__
    name = getattr(callable_, "__name__", str(callable_))
    return _WRAPPED_ENGINE_NAMES.get(name, name)


@router.get("/pipeline", response_model=PipelineResponse)
def get_pipeline() -> PipelineResponse:
    stages: list[PipelineStageOut] = []
    for order, s in enumerate(ALL_STAGES, start=1):
        if s.kind == "fact":
            engines = _FACT_STAGE_ENGINES.get(s.name, [])
        else:
            engines = [_engine_name(c) for c in s.callables]
        stages.append(
            PipelineStageOut(
                name=s.name,
                kind=s.kind,
                order=order,
                engines=engines,
                # Matches app/jobs/runner.py's own literal condition
                # (`optional=(s.name == "security")`) -- "security" is the
                # only stage a third-party outage may fail without failing
                # the whole run.
                optional=(s.name == "security"),
                description=_STAGE_DESCRIPTIONS.get(s.name, ""),
            )
        )
    return PipelineResponse(stages=stages)


assert len(ALL_STAGES) == 13, "CLAUDE.md and the How-it-works page both say thirteen stages"
assert {s.name for s in FACT_STAGES} == set(_FACT_STAGE_ENGINES)


# ---- GET /meta/worked-example ----------------------------------------------


@router.get("/worked-example", response_model=WorkedExampleResponse | None)
def get_worked_example(db: Session = Depends(get_db)) -> WorkedExampleResponse | None:
    """Threads one real, pinned showcase repository through every stage's
    real, already-persisted numbers -- the lowest `showcase_rank` repo that
    has actually reached a `ready` run (`current_run_id` is only ever set
    once a run reaches `ready`, same fact `GET /repos/showcase` already
    relies on). Returns `None` (a plain 200) rather than a 404 when no such
    repository exists yet, so `HowItWorksPage` can degrade to prose instead
    of erroring -- see that page's own handling.

    Every figure below is a direct, honest read of a persisted row for this
    run. Nothing here is computed or estimated -- a field is left `None`
    only when its underlying row genuinely doesn't exist for this run.
    """
    repo = db.scalar(
        select(RepoModel)
        .where(RepoModel.is_showcase.is_(True), RepoModel.current_run_id.isnot(None))
        .order_by(RepoModel.showcase_rank.asc().nulls_last(), RepoModel.created_at.asc())
    )
    if repo is None or repo.current_run_id is None:
        return None

    run_id = repo.current_run_id

    def count(model: Any, *filters: Any) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*filters)) or 0

    subsystem_rows = db.scalars(
        select(Subsystem).where(Subsystem.analysis_run_id == run_id).order_by(Subsystem.rank.asc())
    ).all()

    health_row = db.scalar(select(Health).where(Health.analysis_run_id == run_id))
    passport_row = db.scalar(select(RepoPassport).where(RepoPassport.analysis_run_id == run_id))
    truck_factor_value = db.scalar(
        select(TruckFactor.value).where(TruckFactor.analysis_run_id == run_id)
    )

    return WorkedExampleResponse(
        repo=WorkedExampleRepoOut(id=repo.id, owner=repo.owner, name=repo.name, url=repo.url),
        run_id=run_id,
        commit_count=count(Commit, Commit.repo_id == repo.id),
        file_count=count(File, File.repo_id == repo.id),
        path_count=count(RepoPath, RepoPath.repo_id == repo.id),
        symbol_count=count(Symbol, Symbol.repo_id == repo.id),
        dependency_edge_count=count(Dependency, Dependency.repo_id == repo.id),
        coupling_pair_count=count(Coupling, Coupling.analysis_run_id == run_id),
        subsystem_count=len(subsystem_rows),
        subsystem_labels=[s.label for s in subsystem_rows] or None,
        cycle_count=health_row.cycle_count if health_row else None,
        hidden_dependency_count=health_row.hidden_dependency_count if health_row else None,
        entry_point_count=count(EntryPoint, EntryPoint.analysis_run_id == run_id),
        hotspot_count=count(Finding, Finding.analysis_run_id == run_id, Finding.category == "risk"),
        contributor_count=count(Contributor, Contributor.analysis_run_id == run_id),
        truck_factor=truck_factor_value,
        tour_stop_count=count(TourStop, TourStop.analysis_run_id == run_id),
        glossary_term_count=count(GlossaryTerm, GlossaryTerm.analysis_run_id == run_id),
        health_score=health_row.score if health_row else None,
        onboarding_difficulty=passport_row.onboarding_difficulty if passport_row else None,
        secret_hit_count=count(SecretHit, SecretHit.repo_id == repo.id),
        vulnerability_count=count(Vulnerability, Vulnerability.analysis_run_id == run_id),
        finding_count=count(Finding, Finding.analysis_run_id == run_id),
    )


__all__ = ["router"]
