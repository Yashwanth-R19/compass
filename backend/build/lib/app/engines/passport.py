"""Repo passport and onboarding difficulty score (session 06, Part D).

``PassportEngine`` runs LAST among the onboarding engines and is pure
aggregation over what every earlier engine in this run already computed --
Coupling, Subsystems, Architecture/EntryPoints, Risk, Knowledge, and (in the
SAME "onboarding" stage, immediately before this engine) Health. It adds no
new computation beyond the onboarding-difficulty composite itself.

``RepoPassportData`` is a Pydantic model, validated before ``data`` is ever
persisted -- this engine never hand-builds the stored dict, per the session
spec ("do not hand-build dicts").

**Onboarding difficulty is EXPLICITLY HEURISTIC** (plan/RULES.md sec 3), NOT
locked by master-context.md, which specifies only the Onboarding Difficulty
Score row's *inputs* (coupling density + subsystem count + complexity + doc
coverage), never a formula. The weights below (0.25/0.20/0.20/0.20/0.15) are
a documented starting point, exactly the same honesty convention
``HealthEngine`` already uses for its own composite -- do not treat them as
sacred the way the coupling/risk formulas are, but do not silently
re-tune them either; if a future session changes them, it should say so.
``norm()`` comes from the injected ``BaselineProvider`` for every term the
formula itself wraps in ``norm(...)`` (subsystem_count, median_file_complexity,
max_dependency_depth) -- NEVER hardcoded min/max math in this engine, same
seam ``RiskEngine`` depends on. ``doc_coverage`` and ``truck_factor`` are
already naturally bounded to ``[0, 1]`` by their own arithmetic (a coverage
fraction; ``min(1, truck_factor / 4)``), so the formula does not wrap them in
``norm()`` either -- only three of the five terms go through the provider,
matching the formula exactly as specified.

**Judgement call: the "now" for cadence/dormancy is the run's own
``analysis_runs.started_at``, never ``datetime.now()``.** The engine
contract (CLAUDE.md, app/engines/base.py) forbids "clock-dependent behaviour
beyond reading stored timestamps" -- calling ``datetime.now()`` directly
would make ``compute_passport`` a function of wall-clock time, not of the
persisted facts, breaking the same purity guarantee every other engine
relies on. ``analysis_runs.started_at`` IS a stored timestamp, written once
when the run was created and never touched again, so reading it keeps this
engine pure for a given ``run_id`` (repeated calls against the SAME run_id
always return the same answer) while still giving a genuinely time-relative
recency signal -- re-analysing the same repo a month later legitimately
computes a different ``commits_last_30d``/``is_dormant``, which is correct,
not a bug: it answers "how active does this repo look as of when THIS run
was computed", not "as of some fixed point in the commit history" the way
``is_stale_relative_to_repo`` (session 05, relative to the repo's own last
commit) does for a different question (has any one CONTRIBUTOR gone quiet
relative to the project's own timeline).

**Division by zero is guarded at every one of these sites** (session 06
Known Hazard #2 -- the reason the 1-file/1-commit test exists):
``churn_concentration`` (zero total churn), ``subsystem_spread`` scoring
lives in glossary.py not here, ``truck_factor / 4`` (truck_factor is always
an int >= 0), ``median`` of an empty/singleton list, and every
``norm()``/``risk_normalizer`` call already guards a constant-or-empty input
inside ``HeuristicBaseline`` itself (see app/baseline/heuristic.py).
"""

from __future__ import annotations

import uuid
from collections import Counter, deque
from collections.abc import Sequence
from itertools import pairwise
from math import ceil
from statistics import median
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.baseline.base import BaselineProvider
from app.baseline.heuristic import HeuristicBaseline, size_bucket_for
from app.db.models import (
    AnalysisRun,
    AnalysisStage,
    Commit,
    Contributor,
    EntryPoint,
    File,
    FileExpertise,
    FileMetrics,
    Health,
    Repo,
    RepoManifest,
    RepoPassport,
    RepoPath,
    Subsystem,
    TruckFactor,
)
from app.engines.base import Engine

if TYPE_CHECKING:
    from app.engines.context import RunContext

DORMANT_AFTER_DAYS = 180
"""HEURISTIC: matches expertise.py's STALE_AFTER_DAYS by product coincidence
(both encode "half a year of silence reads as gone quiet"), not by import --
this constant answers a different question (is the whole PROJECT dormant as
of when this run was computed) than that one (has a CONTRIBUTOR gone stale
relative to the repo's own history), so it is deliberately its own named
constant rather than a reused import."""

MAX_TOP_CONTRIBUTORS = 5
"""Judgement call (session 06): the prompt's `top_contributors` field names
no cap. Capped at 5 for the same anti-alert-fatigue reason every other list
in this codebase is capped -- a passport is a one-page summary, not a full
contributor roster (that's what GET /repos/{id}/contributors is for)."""

TOP_RISK_FILES_COUNT = 5
"""Matches the session prompt's own internal reference ("any top-5 risk file
whose only expert is stale", the ORPHANED_HOTSPOT rule below) -- one shared
constant rather than a magic "5" repeated in two places."""

HIGH_CHURN_CONCENTRATION_THRESHOLD = 0.5
LOW_TRUCK_FACTOR_THRESHOLD = 2
LOW_COHESION_SUBSYSTEM_THRESHOLD = 0.4
"""Product thresholds given directly by the session prompt for the
``first_pr`` rules -- not independently chosen HEURISTIC values in the
plan/RULES.md sec 3 sense, and not literature-cited either (same "given
directly" bucket session 05's single-expert-subsystem/knowledge-concentration
ratios landed in)."""


# ---- Pydantic model for `repo_passport.data` -- validated, never hand-built ----


class PassportIdentity(BaseModel):
    name: str
    owner: str
    url: str
    primary_language: str
    language_breakdown: dict[str, int]
    license_spdx: str | None
    has_readme: bool
    readme_lines: int


class PassportScale(BaseModel):
    files: int
    loc: int
    commits: int
    contributors: int
    subsystems: int
    age_days: float
    first_commit_at: str | None
    last_commit_at: str | None


class PassportCadence(BaseModel):
    commits_last_30d: int
    commits_last_90d: int
    commits_last_365d: int
    median_commits_per_active_week: float
    active_days: int
    longest_gap_days: float
    is_dormant: bool


class PassportTopContributor(BaseModel):
    name: str
    share: float
    is_stale: bool


class PassportTeam(BaseModel):
    active_contributors: int
    stale_contributors: int
    bot_commit_ratio: float
    truck_factor: int
    top_contributors: list[PassportTopContributor]


class PassportSubsystemSummary(BaseModel):
    label: str
    file_count: int
    cohesion: float


class PassportEntryPointSummary(BaseModel):
    path: str
    kind: str


class PassportShape(BaseModel):
    subsystems: list[PassportSubsystemSummary]
    entry_points: list[PassportEntryPointSummary]
    modularity: float


class PassportHotspotFile(BaseModel):
    path: str
    risk_score: float
    risk_confidence: float


class PassportHotspots(BaseModel):
    top_risk_files: list[PassportHotspotFile]
    churn_concentration: float


class PassportHealth(BaseModel):
    score: float
    high_risk_ratio: float
    cycle_count: int
    hidden_dependency_count: int
    calibration: str


class PassportFirstPrItem(BaseModel):
    """A structured orientation fact -- a CODE plus its backing PARAMS, never
    a rendered sentence. Session 08 owns the wording (lib/copy.ts, with an
    exhaustiveness test there) -- if you find yourself writing English into
    this engine, stop (session 06 Known Hazard #7)."""

    code: str
    params: dict[str, Any]


class RepoPassportData(BaseModel):
    identity: PassportIdentity
    scale: PassportScale
    cadence: PassportCadence
    team: PassportTeam
    shape: PassportShape
    hotspots: PassportHotspots
    health: PassportHealth
    first_pr: list[PassportFirstPrItem]


# ---- Helpers ----


def _select_primary_manifest(
    repo_id: uuid.UUID, session: Session, kind: str
) -> tuple[int, str, dict[str, Any]] | None:
    """The repo's primary README/LICENSE, when ``repo_manifests`` has one --
    a monorepo can have several (session 03's manifest walk isn't root-only),
    so the shallowest path wins, tie-broken by path asc for determinism.
    Shared by both manifest kinds this engine reads; see
    ``app/engines/tour.py::_select_primary_readme`` for the same small
    selection rule applied to just the README case there -- duplicated
    rather than imported across engine modules, since each call site wants a
    different data shape out of the result."""
    rows = session.execute(
        select(RepoManifest.path_id, RepoPath.path, RepoManifest.data)
        .join(RepoPath, RepoPath.id == RepoManifest.path_id)
        .where(RepoManifest.repo_id == repo_id, RepoManifest.kind == kind)
    ).all()
    if not rows:
        return None
    best = min(rows, key=lambda r: (r[1].count("/"), r[1]))
    return best[0], best[1], best[2]


def _median(values: list[float]) -> float:
    """``statistics.median`` raises on an empty list -- 0.0 instead, the
    same "no data, no crash" discipline every degenerate case in this
    session follows."""
    return median(values) if values else 0.0


def _max_dependency_depth(graph: Any, entry_paths: list[str]) -> int:
    """The longest shortest-path from ANY entry point in the dependency
    graph (Part D's own wording) -- a multi-source BFS eccentricity, not a
    per-entry-point max. 0 for a graph with no edges or no entry points at
    all, never a crash."""
    dist: dict[str, int] = {}
    queue: deque[str] = deque()
    for p in entry_paths:
        if p in graph and p not in dist:
            dist[p] = 0
            queue.append(p)
    max_depth = 0
    while queue:
        node = queue.popleft()
        for nxt in graph.successors(node):
            if nxt not in dist:
                dist[nxt] = dist[node] + 1
                max_depth = max(max_depth, dist[nxt])
                queue.append(nxt)
    return max_depth


def _has_contributing_or_docs(file_paths: list[str]) -> bool:
    for path in file_paths:
        segments = path.split("/")
        if segments[0].lower() == "docs":
            return True
        if segments[-1].upper().startswith("CONTRIBUTING"):
            return True
    return False


def compute_passport(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    session: Session,
    ctx: RunContext,
    baseline: BaselineProvider,
) -> tuple[RepoPassportData, float, dict[str, Any]]:
    """Pure computation (no writes) -- the module-level ``compute_*`` core
    every engine follows. Returns ``(data, onboarding_difficulty,
    difficulty_breakdown)``."""
    repo = session.get(Repo, repo_id)
    assert repo is not None

    files = session.scalars(
        select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
    ).all()
    file_paths = [f.path for f in files]

    commit_times = session.scalars(
        select(Commit.committed_at).where(Commit.repo_id == repo_id).order_by(Commit.committed_at)
    ).all()

    run = session.get(AnalysisRun, run_id)
    assert run is not None
    reference_now = run.started_at

    # ---- identity ----
    dominant_language = (
        Counter(f.language for f in files).most_common(1)[0][0] if files else "other"
    )
    language_breakdown = dict(Counter(f.language for f in files))

    readme = _select_primary_manifest(repo_id, session, "readme")
    has_readme = readme is not None
    readme_lines = readme[2].get("line_count", 0) if readme is not None else 0

    license_row = _select_primary_manifest(repo_id, session, "license")
    license_spdx = license_row[2].get("spdx_id") if license_row is not None else None

    identity = PassportIdentity(
        name=repo.name,
        owner=repo.owner,
        url=repo.url,
        primary_language=dominant_language,
        language_breakdown=language_breakdown,
        license_spdx=license_spdx,
        has_readme=has_readme,
        readme_lines=readme_lines,
    )

    # ---- scale ----
    subsystem_count = len(
        session.scalars(select(Subsystem.id).where(Subsystem.analysis_run_id == run_id)).all()
    )

    contributor_rows = session.scalars(
        select(Contributor).where(Contributor.analysis_run_id == run_id)
    ).all()

    scale = PassportScale(
        files=len(files),
        loc=sum(f.current_loc for f in files),
        commits=len(commit_times),
        contributors=len(contributor_rows),
        subsystems=subsystem_count,
        age_days=(
            (commit_times[-1] - commit_times[0]).total_seconds() / 86400
            if len(commit_times) >= 2
            else 0.0
        ),
        first_commit_at=commit_times[0].isoformat() if commit_times else None,
        last_commit_at=commit_times[-1].isoformat() if commit_times else None,
    )

    # ---- cadence ----
    def _commits_since(days: int) -> int:
        cutoff = reference_now.timestamp() - days * 86400
        return sum(1 for t in commit_times if t.timestamp() >= cutoff)

    weeks: Counter[tuple[int, int]] = Counter()
    dates: set[Any] = set()
    for t in commit_times:
        weeks[t.isocalendar()[:2]] += 1
        dates.add(t.date())
    sorted_dates = sorted(dates)
    longest_gap = 0.0
    for prev, nxt in pairwise(sorted_dates):
        longest_gap = max(longest_gap, (nxt - prev).days)

    days_since_last_commit = (
        (reference_now - commit_times[-1]).total_seconds() / 86400 if commit_times else float("inf")
    )

    cadence = PassportCadence(
        commits_last_30d=_commits_since(30),
        commits_last_90d=_commits_since(90),
        commits_last_365d=_commits_since(365),
        median_commits_per_active_week=_median([float(c) for c in weeks.values()]),
        active_days=len(dates),
        longest_gap_days=longest_gap,
        is_dormant=days_since_last_commit > DORMANT_AFTER_DAYS,
    )

    # ---- team ----
    total_commits = len(commit_times)
    bot_commits = sum(c.commit_count for c in contributor_rows if c.is_bot)
    truck_factor_row = session.scalar(
        select(TruckFactor).where(TruckFactor.analysis_run_id == run_id)
    )
    truck_factor = truck_factor_row.value if truck_factor_row is not None else 0

    ranked_contributors = sorted(contributor_rows, key=lambda c: c.rank)[:MAX_TOP_CONTRIBUTORS]
    top_contributors = [
        PassportTopContributor(
            name=c.canonical_name,
            share=(c.commit_count / total_commits) if total_commits else 0.0,
            is_stale=c.is_stale,
        )
        for c in ranked_contributors
    ]

    team = PassportTeam(
        active_contributors=sum(1 for c in contributor_rows if not c.is_bot and not c.is_stale),
        stale_contributors=sum(1 for c in contributor_rows if not c.is_bot and c.is_stale),
        bot_commit_ratio=(bot_commits / total_commits) if total_commits else 0.0,
        truck_factor=truck_factor,
        top_contributors=top_contributors,
    )

    # ---- shape ----
    subsystem_rows = session.scalars(
        select(Subsystem).where(Subsystem.analysis_run_id == run_id).order_by(Subsystem.rank)
    ).all()
    entry_point_rows = session.execute(
        select(EntryPoint.path_id, EntryPoint.kind, RepoPath.path)
        .join(RepoPath, RepoPath.id == EntryPoint.path_id)
        .where(EntryPoint.analysis_run_id == run_id)
        .order_by(EntryPoint.rank)
    ).all()
    stage_row = session.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == "subsystems"
        )
    )
    modularity = (stage_row.summary or {}).get("modularity", 0.0) if stage_row is not None else 0.0

    shape = PassportShape(
        subsystems=[
            PassportSubsystemSummary(label=s.label, file_count=s.file_count, cohesion=s.cohesion)
            for s in subsystem_rows
        ],
        entry_points=[
            PassportEntryPointSummary(path=path, kind=kind) for _pid, kind, path in entry_point_rows
        ],
        modularity=modularity,
    )

    # ---- hotspots ----
    risk_rows = session.execute(
        select(File.path, FileMetrics.path_id, FileMetrics.risk_score, FileMetrics.risk_confidence)
        .join(
            FileMetrics,
            (FileMetrics.path_id == File.path_id) & (FileMetrics.analysis_run_id == run_id),
        )
        .where(File.repo_id == repo_id, File.is_deleted.is_(False))
        .order_by(FileMetrics.hotspot_rank)
        .limit(TOP_RISK_FILES_COUNT)
    ).all()
    top_risk_files = [
        PassportHotspotFile(path=path, risk_score=score, risk_confidence=confidence)
        for path, _pid, score, confidence in risk_rows
    ]

    total_churn = sum(f.churn_total for f in files)
    if files and total_churn > 0:
        top_n = max(1, ceil(0.1 * len(files)))
        top_churn = sum(sorted((f.churn_total for f in files), reverse=True)[:top_n])
        churn_concentration = top_churn / total_churn
    else:
        churn_concentration = 0.0

    hotspots = PassportHotspots(
        top_risk_files=top_risk_files, churn_concentration=churn_concentration
    )

    # ---- health ----
    health_row = session.scalar(select(Health).where(Health.analysis_run_id == run_id))
    health = PassportHealth(
        score=health_row.score if health_row is not None else 0.0,
        high_risk_ratio=health_row.high_risk_ratio if health_row is not None else 0.0,
        cycle_count=health_row.cycle_count if health_row is not None else 0,
        hidden_dependency_count=health_row.hidden_dependency_count if health_row is not None else 0,
        calibration="heuristic",
    )

    # ---- first_pr ----
    first_pr = _compute_first_pr(
        session=session,
        run_id=run_id,
        churn_concentration=churn_concentration,
        truck_factor=truck_factor,
        top_risk_path_ids=[pid for _p, pid, _s, _c in risk_rows],
        risk_path_by_id={pid: path for path, pid, _s, _c in risk_rows},
        hidden_dependency_count=health.hidden_dependency_count,
        cycle_count=health.cycle_count,
        days_since_last_commit=days_since_last_commit,
        entry_point_kinds={kind for _pid, kind, _path in entry_point_rows},
        subsystem_rows=subsystem_rows,
    )

    data = RepoPassportData(
        identity=identity,
        scale=scale,
        cadence=cadence,
        team=team,
        shape=shape,
        hotspots=hotspots,
        health=health,
        first_pr=first_pr,
    )

    # ---- onboarding difficulty (EXPLICITLY HEURISTIC, see module docstring) ----
    size_bucket = size_bucket_for(len(files))
    median_complexity = _median([f.complexity for f in files])
    max_dep_depth = _max_dependency_depth(
        ctx.dependency_graph(session), [path for _pid, _kind, path in entry_point_rows]
    )
    doc_coverage = (
        (0.5 if has_readme else 0.0)
        + (0.25 if readme_lines > 100 else 0.0)
        + (0.25 if _has_contributing_or_docs(file_paths) else 0.0)
    )

    norm_subsystem_count = baseline.risk_normalizer(
        "subsystem_count", dominant_language, size_bucket
    )([float(subsystem_count)])[0]
    norm_median_complexity = baseline.risk_normalizer(
        "median_file_complexity", dominant_language, size_bucket
    )([median_complexity])[0]
    norm_max_dep_depth = baseline.risk_normalizer(
        "max_dependency_depth", dominant_language, size_bucket
    )([float(max_dep_depth)])[0]

    truck_factor_component = 1.0 - min(1.0, truck_factor / 4)
    doc_coverage_component = 1.0 - doc_coverage

    difficulty = 100.0 * (
        0.25 * norm_subsystem_count
        + 0.20 * norm_median_complexity
        + 0.20 * doc_coverage_component
        + 0.20 * truck_factor_component
        + 0.15 * norm_max_dep_depth
    )

    breakdown = {
        "subsystem_count": {
            "raw": subsystem_count,
            "normalized": norm_subsystem_count,
            "weight": 0.25,
        },
        "median_file_complexity": {
            "raw": median_complexity,
            "normalized": norm_median_complexity,
            "weight": 0.20,
        },
        "doc_coverage": {
            "raw": doc_coverage,
            "normalized": doc_coverage_component,
            "weight": 0.20,
        },
        "truck_factor": {
            "raw": truck_factor,
            "normalized": truck_factor_component,
            "weight": 0.20,
        },
        "max_dependency_depth": {
            "raw": max_dep_depth,
            "normalized": norm_max_dep_depth,
            "weight": 0.15,
        },
    }

    return data, difficulty, breakdown


def _compute_first_pr(
    *,
    session: Session,
    run_id: uuid.UUID,
    churn_concentration: float,
    truck_factor: int,
    top_risk_path_ids: list[int],
    risk_path_by_id: dict[int, str],
    hidden_dependency_count: int,
    cycle_count: int,
    days_since_last_commit: float,
    entry_point_kinds: set[str],
    subsystem_rows: Sequence[Subsystem],
) -> list[PassportFirstPrItem]:
    """Session 06 Part D: eight rules, evaluated in this FIXED priority
    order, top 3 that fire kept -- structured ``{code, params}`` objects
    only, never rendered sentences (Known Hazard #7; session 08 owns the
    wording)."""
    items: list[PassportFirstPrItem] = []

    def _maybe(code: str, fires: bool, params: dict[str, Any]) -> None:
        if fires and len(items) < 3:
            items.append(PassportFirstPrItem(code=code, params=params))

    _maybe(
        "HIGH_CHURN_CONCENTRATION",
        churn_concentration > HIGH_CHURN_CONCENTRATION_THRESHOLD,
        {"churn_concentration": churn_concentration},
    )
    _maybe(
        "LOW_TRUCK_FACTOR",
        truck_factor <= LOW_TRUCK_FACTOR_THRESHOLD,
        {"truck_factor": truck_factor},
    )

    orphaned_path: str | None = None
    if top_risk_path_ids:
        expert_rows = session.execute(
            select(FileExpertise.path_id, FileExpertise.contributor_id, Contributor.is_stale)
            .join(Contributor, Contributor.id == FileExpertise.contributor_id)
            .where(
                FileExpertise.analysis_run_id == run_id,
                FileExpertise.path_id.in_(top_risk_path_ids),
                FileExpertise.is_expert.is_(True),
            )
        ).all()
        experts_by_path: dict[int, list[bool]] = {}
        for path_id, _cid, is_stale in expert_rows:
            experts_by_path.setdefault(path_id, []).append(is_stale)
        for path_id in top_risk_path_ids:
            stales = experts_by_path.get(path_id, [])
            if len(stales) == 1 and stales[0]:
                orphaned_path = risk_path_by_id.get(path_id)
                break
    _maybe(
        "ORPHANED_HOTSPOT",
        orphaned_path is not None,
        {"path": orphaned_path},
    )

    _maybe(
        "HIDDEN_DEPENDENCIES",
        hidden_dependency_count > 0,
        {"count": hidden_dependency_count},
    )
    _maybe(
        "CIRCULAR_DEPENDENCIES",
        cycle_count > 0,
        {"count": cycle_count},
    )
    _maybe(
        "DORMANT",
        days_since_last_commit > DORMANT_AFTER_DAYS,
        {"days_since_last_commit": days_since_last_commit},
    )
    _maybe(
        "NO_TESTS",
        "test_root" not in entry_point_kinds,
        {},
    )

    low_cohesion = next(
        (s for s in subsystem_rows if s.cohesion < LOW_COHESION_SUBSYSTEM_THRESHOLD), None
    )
    _maybe(
        "LOW_COHESION_SUBSYSTEM",
        low_cohesion is not None,
        {
            "label": low_cohesion.label if low_cohesion else None,
            "cohesion": low_cohesion.cohesion if low_cohesion else None,
        },
    )

    return items[:3]


class PassportEngine(Engine):
    """Pure aggregation over every other engine's output for this run
    (session 06, Part D) -- see the module docstring for why this must run
    after ``HealthEngine`` (reads its persisted row) and for the
    run-started_at "now" judgement call behind cadence/dormancy.
    """

    def __init__(self, baseline: BaselineProvider | None = None) -> None:
        self._baseline = baseline or HeuristicBaseline()

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        data, difficulty, breakdown = compute_passport(
            ctx.repo_id, ctx.run_id, session, ctx, self._baseline
        )
        session.execute(
            insert(RepoPassport).values(
                analysis_run_id=ctx.run_id,
                repo_id=ctx.repo_id,
                data=data.model_dump(mode="json"),
                onboarding_difficulty=difficulty,
                difficulty_breakdown=breakdown,
            )
        )
        return {
            "onboarding_difficulty": difficulty,
            "files": data.scale.files,
            "subsystems": data.scale.subsystems,
        }
