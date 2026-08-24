import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, AnalysisRunStatus, AnalysisStage, StageStatus
from app.engines.architecture import ArchEngine
from app.engines.context import RunContext
from app.engines.coupling import CouplingEngine
from app.engines.entrypoints import EntryPointEngine
from app.engines.expertise import ExpertiseEngine
from app.engines.findings import FindingsRankEngine
from app.engines.glossary import GlossaryEngine
from app.engines.health import HealthEngine
from app.engines.hygiene import HygieneEngine
from app.engines.module_coupling import ModuleCouplingEngine
from app.engines.overlay import OverlayEngine
from app.engines.passport import PassportEngine
from app.engines.risk import RiskEngine
from app.engines.subsystems import SubsystemEngine
from app.engines.test_gaps import TestGapEngine
from app.engines.tour import TourEngine
from app.engines.truck_factor import TruckFactorEngine

StageKind = Literal["fact", "insight"]

EngineCallable = Callable[[RunContext, Session], dict[str, Any]]


@dataclass(frozen=True)
class Stage:
    """One entry in the canonical, ordered stage list (Phase 02, CLAUDE.md).

    ``callables`` is only populated for "insight" stages, where every
    engine already shares the uniform ``Engine.run(ctx, session) -> dict``
    signature (app/engines/base.py) -- letting the runner drive them
    generically: ``for c in s.callables: summary.update(c(ctx, session))``.
    A stage can run SEVERAL engines in a fixed sequence (session 04: the
    "subsystems" stage runs SubsystemEngine then ModuleCouplingEngine, the
    "architecture" stage runs ArchEngine then EntryPointEngine then
    OverlayEngine) -- the one-engine-per-stage assumption from earlier
    sessions no longer holds. The tuple's own order IS the execution order
    within that stage; when a later engine in the tuple depends on an
    earlier one's output for this SAME run_id (e.g. ModuleCouplingEngine's
    subsystem-granularity pass needs SubsystemEngine's partition), that
    order is load-bearing, not incidental -- don't reorder it.

    "fact" stages (clone/mine/structure/persist_facts) have no such uniform
    signature -- each one both consumes and produces different local state
    (a clone path, a MinedRepo, a dependency list) that has to thread
    through to the next stage -- so ``run_ingestion_job`` runs their bodies
    inline instead of through this field, and it is left empty.
    """

    name: str
    kind: StageKind
    callables: tuple[EngineCallable, ...] = ()


FACT_STAGES: tuple[Stage, ...] = (
    Stage("clone", "fact"),
    Stage("mine", "fact"),
    Stage("structure", "fact"),
    Stage("persist_facts", "fact"),
)

INSIGHT_STAGES: tuple[Stage, ...] = (
    Stage("coupling", "insight", (CouplingEngine().run,)),
    Stage("subsystems", "insight", (SubsystemEngine().run, ModuleCouplingEngine().run)),
    Stage(
        "architecture", "insight", (ArchEngine().run, EntryPointEngine().run, OverlayEngine().run)
    ),
    Stage("risk", "insight", (RiskEngine().run, HygieneEngine().run, TestGapEngine().run)),
    Stage("knowledge", "insight", (ExpertiseEngine().run, TruckFactorEngine().run)),
    Stage(
        "onboarding",
        "insight",
        (TourEngine().run, GlossaryEngine().run, HealthEngine().run, PassportEngine().run),
    ),
    Stage("rank", "insight", (FindingsRankEngine().run,)),
)
"""Fixed order, load-bearing (CLAUDE.md "Engines" section):

- "subsystems" needs Coupling's persisted rows (SubsystemEngine's graph
  weights coupling pairs alongside structural edges); within it,
  SubsystemEngine must run before ModuleCouplingEngine, which reads the
  subsystem partition SubsystemEngine just wrote (session 04, Known Hazard
  #3 -- the two engines sharing one stage does not by itself guarantee
  order, the tuple order does).
- "architecture" needs Coupling (Overlay, which now lives in this stage,
  joins coupling against dependencies); within it, ArchEngine builds the
  dependency graph EntryPointEngine reuses off the shared RunContext
  (avoiding a second graph build), and OverlayEngine runs last since it
  also depends on ArchEngine's structural edges for the hidden-dependency
  join.
- "risk" needs Coupling's max coupling_degree per file. Within it (session
  07), RiskEngine must run FIRST -- HygieneEngine and TestGapEngine both
  UPDATE the ``file_metrics`` rows RiskEngine inserts for this run_id
  (never insert their own; the unique constraint on
  (analysis_run_id, path_id) would reject a second insert). TestGapEngine
  additionally reads ``file_metrics.risk_score`` (for its top-risk-quartile
  finding) and must therefore run AFTER RiskEngine has written it; it runs
  after HygieneEngine too, but the two don't depend on each other -- that
  relative order is fixed only because it's the order the session prompt
  named them in.
- "knowledge" (session 05) needs Risk's file_metrics.risk_score (the
  orphaned-knowledge finding) and Subsystems' partition (the
  single-expert-subsystem finding) -- MUST run after both, hence its
  placement here, after "risk". Within it, ExpertiseEngine must run before
  TruckFactorEngine, which reads the file_expertise/contributors rows
  ExpertiseEngine just wrote for this same run_id (Avelino's greedy
  algorithm never recomputes DOA itself). run_ingestion_job skips this
  whole stage (StageStatus.skipped, not run) when the repo has zero
  commits -- see that module's Part D degenerate-case handling.
- "onboarding" (session 06) folds the former standalone "health" stage in
  alongside the two new onboarding engines -- TourEngine and GlossaryEngine
  both read Coupling/Subsystems/Architecture/Risk/Knowledge output from
  earlier stages but don't depend on each other or on Health, so they run
  first (in this fixed relative order for no reason beyond "Tour before
  Glossary" being the order the session prompt names them in -- neither
  actually reads the other's output). HealthEngine runs third, UNCHANGED
  from its pre-session-06 behavior (needs Risk's file_metrics plus
  Architecture's cycles and Overlay's hidden-dependency count -- see its own
  docstring). **PassportEngine runs FOURTH, strictly after HealthEngine, in
  the SAME stage** -- this is the one new load-bearing order dependency
  session 06 introduces: PassportEngine's ``data.health`` embeds the
  ``health`` row HealthEngine writes earlier in this same stage, and the
  onboarding-difficulty formula's inputs are otherwise all already-computed
  by that point. Reordering PassportEngine ahead of HealthEngine within this
  tuple would make it read a row that doesn't exist yet for this run_id.
- "rank" needs every other engine's findings already written for this
  run_id.

Do not reorder."""

ALL_STAGES: tuple[Stage, ...] = FACT_STAGES + INSIGHT_STAGES


def create_pending_stages(run_id: uuid.UUID, session: Session) -> None:
    """Pre-create every analysis_stages row as ``pending``, in canonical
    order, before any work starts -- so the very first ``/repos/{id}/status``
    poll can render the full stage list with skeletons instead of the
    frontend guessing what's coming (Part F, progressive reveal)."""
    session.execute(
        insert(AnalysisStage),
        [{"run_id": run_id, "name": s.name, "status": StageStatus.pending} for s in ALL_STAGES],
    )


def _get_stage_row(run_id: uuid.UUID, name: str, session: Session) -> AnalysisStage:
    row = session.scalar(
        select(AnalysisStage).where(AnalysisStage.run_id == run_id, AnalysisStage.name == name)
    )
    if row is None:
        raise RuntimeError(
            f"analysis_stages row for (run_id={run_id}, name={name!r}) was not "
            "pre-created -- create_pending_stages() must run before any stage()."
        )
    return row


@contextmanager
def stage(run_id: uuid.UUID, name: str, session: Session) -> Iterator[dict[str, Any]]:
    """Marks the ``analysis_stages`` row for ``(run_id, name)`` running ->
    done/failed, COMMITTING at each transition -- the commit-per-stage is
    the whole point of progressive reveal (Part B of the phase spec); never
    batch these into one transaction at the end.

    Yields a mutable ``dict`` the caller fills in as the stage's summary
    (counts, flags, ...); on success it's stored verbatim as the row's
    ``summary`` JSONB. On exception, the stage row AND the owning
    ``analysis_runs`` row are marked failed (with the exception's message)
    and committed, and the exception re-raises so ``run_ingestion_job``'s
    outer handler can still do its own cleanup (deleting the clone) and mark
    the ``jobs``/``repos`` rows -- crucially, WITHOUT touching
    ``repos.current_run_id``, so a failed re-analysis never blanks out a
    repo that already had a good run (Part C, step 7).
    """
    row = _get_stage_row(run_id, name, session)
    row.status = StageStatus.running
    row.started_at = datetime.now(UTC)
    session.commit()

    summary: dict[str, Any] = {}
    try:
        yield summary
    except Exception as exc:
        session.rollback()
        row = _get_stage_row(run_id, name, session)
        row.status = StageStatus.failed
        row.finished_at = datetime.now(UTC)
        row.error = str(exc)

        run = session.get(AnalysisRun, run_id)
        if run is not None:
            run.status = AnalysisRunStatus.failed
            run.error = str(exc)
            run.finished_at = datetime.now(UTC)

        session.commit()
        raise
    else:
        row.status = StageStatus.done
        row.finished_at = datetime.now(UTC)
        row.summary = summary
        session.commit()


def mark_stage_skipped(
    run_id: uuid.UUID, name: str, session: Session, summary: dict[str, Any]
) -> None:
    """Marks a FACT stage ``skipped`` when ``run_ingestion_job`` decides an
    unchanged ``head_sha`` means cloning/mining can be skipped entirely --
    the re-analysis-is-nearly-instant feature (Part C, step 3)."""
    row = _get_stage_row(run_id, name, session)
    row.status = StageStatus.skipped
    row.started_at = datetime.now(UTC)
    row.finished_at = datetime.now(UTC)
    row.summary = summary
    session.commit()
