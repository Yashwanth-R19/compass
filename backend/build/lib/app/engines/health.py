import uuid
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.db.models import File, FileMetrics, Health
from app.engines.base import Engine
from app.engines.context import RunContext

HIGH_RISK_THRESHOLD = 0.60
"""A file counts toward the "high risk" proportion once its composite
risk_score (app/engines/risk.py) reaches this. Independent of RiskEngine's
own (higher) 0.70 finding-severity threshold -- this one answers "how much
of the repo is concerning", a repo-wide ratio, not "is this one file bad
enough to alert on"."""

RISK_PENALTY_WEIGHT = 40.0
CYCLE_PENALTY_PER_CYCLE = 6.0
CYCLE_PENALTY_CAP = 30.0
HIDDEN_DEP_PENALTY_PER_PAIR = 3.0
HIDDEN_DEP_PENALTY_CAP = 30.0
"""Composite health formula (0-100, higher = healthier), heuristic and
documented like every other cross-cutting score in Compass -- not locked by
master-context.md, which only specifies the *inputs* (proportion of
high-risk files, cycle count, hidden-dependency count; duplication is a
documented future input, not computed yet -- see master-context.md sec 8's
Overview/Health row).

    health_score = 100
                 - min(100, RISK_PENALTY_WEIGHT * high_risk_ratio)
                 - min(CYCLE_PENALTY_CAP, CYCLE_PENALTY_PER_CYCLE * cycle_count)
                 - min(HIDDEN_DEP_PENALTY_CAP, HIDDEN_DEP_PENALTY_PER_PAIR * hidden_dependency_count)
                 , floored at 0

Risk gets the largest single penalty budget (40 of 100 points) because
churn*complexity-driven risk is the most-validated signal Compass computes
(same reasoning as risk_score's own 0.60 weight, master-context.md sec 8.1);
cycles and hidden dependencies are capped at 30 points each so a single
tangled but otherwise healthy repo can't be driven all the way to 0 by
structural findings alone.
"""


def _high_risk_ratio(repo_id: uuid.UUID, run_id: uuid.UUID, session: Session) -> float:
    # INVARIANT: the numerator and denominator must always be drawn from the
    # same file population. RiskEngine only ever scores files where
    # is_deleted is false (a deleted file never gets a file_metrics row), so
    # `total` must be scoped the same way -- otherwise a repo with real
    # deletion history understates high_risk_ratio (a deleted-inclusive
    # denominator divided into a deleted-exclusive numerator) -- see
    # CLAUDE.md's health-engine section.
    total = (
        session.scalar(
            select(func.count())
            .select_from(File)
            .where(File.repo_id == repo_id, File.is_deleted.is_(False))
        )
        or 0
    )
    if total == 0:
        return 0.0
    high_risk = (
        session.scalar(
            select(func.count())
            .select_from(FileMetrics)
            .where(
                FileMetrics.repo_id == repo_id,
                FileMetrics.analysis_run_id == run_id,
                FileMetrics.risk_score >= HIGH_RISK_THRESHOLD,
            )
        )
        or 0
    )
    return high_risk / total


def compute_health(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    session: Session,
    *,
    cycle_count: int,
    hidden_dependency_count: int,
) -> dict[str, Any]:
    """Pure computation of the composite health score and its inputs -- no
    writes. Shared by HealthEngine (persists it) and available to callers
    that want it recomputed fresh, same "pure function over mined facts"
    shape as every other engine's compute_* helper. ``run_id`` scopes the
    file_metrics read (via ``_high_risk_ratio``) to this run only -- that
    table holds rows from every past run of this repo (Phase 02).

    ``cycle_count``/``hidden_dependency_count`` are passed in rather than
    recomputed here -- ArchEngine and OverlayEngine already computed them
    for this same run_id (session 01: the whole point of RunContext is that
    HealthEngine no longer re-derives what a prior engine in the same run
    already derived). See HealthEngine.run, which sources both from ctx.
    """
    high_risk_ratio = _high_risk_ratio(repo_id, run_id, session)

    risk_penalty = min(100.0, RISK_PENALTY_WEIGHT * high_risk_ratio)
    cycle_penalty = min(CYCLE_PENALTY_CAP, CYCLE_PENALTY_PER_CYCLE * cycle_count)
    hidden_dep_penalty = min(
        HIDDEN_DEP_PENALTY_CAP, HIDDEN_DEP_PENALTY_PER_PAIR * hidden_dependency_count
    )

    score = max(0.0, 100.0 - risk_penalty - cycle_penalty - hidden_dep_penalty)

    return {
        "score": score,
        "high_risk_ratio": high_risk_ratio,
        "cycle_count": cycle_count,
        "hidden_dependency_count": hidden_dependency_count,
    }


class HealthEngine(Engine):
    """Single 0-100 composite health score from aggregates of the other
    engines' output (master-context.md sec 8, Overview/Health row). Runs
    after Risk (needs file_metrics.risk_score) and after Architecture/Overlay
    (needs cycles/hidden-dependency counts) -- pure DB-only, no recompute of
    those engines' own persisted rows beyond the small, already-shared
    find_cycles/compute_hidden_dependencies helpers.
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id
        cycle_count = len(ctx.cycles(session))
        hidden_dependency_count = len(ctx.hidden_dependencies(session))
        result = compute_health(
            repo_id,
            run_id,
            session,
            cycle_count=cycle_count,
            hidden_dependency_count=hidden_dependency_count,
        )

        session.execute(
            insert(Health),
            [
                {
                    "id": uuid.uuid4(),
                    "analysis_run_id": run_id,
                    "repo_id": repo_id,
                    "score": result["score"],
                    "high_risk_ratio": result["high_risk_ratio"],
                    "cycle_count": result["cycle_count"],
                    "hidden_dependency_count": result["hidden_dependency_count"],
                }
            ],
        )

        return result
