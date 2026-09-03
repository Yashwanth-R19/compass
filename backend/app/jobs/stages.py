import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.baseline.provider import get_baseline_provider
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
from app.engines.security import SecurityEngine, fetch_and_persist_vulnerabilities
from app.engines.subsystems import SubsystemEngine
from app.engines.timeline import TimelineEngine
from app.engines.tour import TourEngine
from app.engines.truck_factor import TruckFactorEngine


def _run_risk_engine(ctx: RunContext, session: Session) -> dict[str, Any]:
    """Session 14: constructs ``RiskEngine`` PER CALL (not at module import
    time, unlike every other engine in ``INSIGHT_STAGES`` below) so its
    injected ``BaselineProvider`` can be ``SeedBaseline``/``CorpusBaseline``
    -- both of which need a live DB session that doesn't exist yet at import
    time. ``app/engines/risk.py`` itself is untouched: this only changes
    WHEN/HOW it's constructed, via the constructor injection it has had
    since session 07."""
    return RiskEngine(baseline=get_baseline_provider(session)).run(ctx, session)


def _run_hygiene_engine(ctx: RunContext, session: Session) -> dict[str, Any]:
    """Same reasoning as ``_run_risk_engine`` -- HygieneEngine's
    ``instability_score`` also goes through the injected BaselineProvider's
    ``norm()`` (CLAUDE.md "Commit hygiene")."""
    return HygieneEngine(baseline=get_baseline_provider(session)).run(ctx, session)


def _run_passport_engine(ctx: RunContext, session: Session) -> dict[str, Any]:
    """Same reasoning again -- PassportEngine's onboarding-difficulty score
    wraps three of its five terms in the injected BaselineProvider's
    ``norm()`` (CLAUDE.md "Repo passport")."""
    return PassportEngine(baseline=get_baseline_provider(session)).run(ctx, session)


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
    Stage("secrets", "fact"),
)
"""Session 10, Part F: ``secrets`` runs LAST among the FACT stages, AFTER
``persist_facts`` -- it needs BOTH the clone (for ``git log -p``) and
interned ``repo_paths`` ids (for ``secret_hits.path_id``), and only
``persist_facts`` produces the second. This is why the clone must now
survive one stage longer than it used to -- see
``app/jobs/runner.py``'s restructured clone-deletion point, moved from
immediately after ``persist_facts`` to immediately after ``secrets``."""

INSIGHT_STAGES: tuple[Stage, ...] = (
    Stage("coupling", "insight", (CouplingEngine().run,)),
    Stage("subsystems", "insight", (SubsystemEngine().run, ModuleCouplingEngine().run)),
    Stage(
        "architecture", "insight", (ArchEngine().run, EntryPointEngine().run, OverlayEngine().run)
    ),
    Stage("risk", "insight", (_run_risk_engine, _run_hygiene_engine)),
    Stage("knowledge", "insight", (ExpertiseEngine().run, TruckFactorEngine().run)),
    Stage(
        "onboarding",
        "insight",
        (
            TourEngine().run,
            GlossaryEngine().run,
            TimelineEngine().run,
            HealthEngine().run,
            _run_passport_engine,
        ),
    ),
    Stage("security", "insight", (fetch_and_persist_vulnerabilities, SecurityEngine().run)),
    Stage("rank", "insight", (FindingsRankEngine().run,)),
)
"""Session 10, Part F: ``security`` is placed LAST before ``rank`` --
deliberately, so its network latency (the OSV.dev lookup) is fully hidden
behind progressive reveal: every other insight tab has already resolved by
the time a user could even notice this one is still working.
``fetch_and_persist_vulnerabilities`` (app/engines/security.py) is NOT an
``Engine`` -- it's the one deliberate exception to "every insight stage is
pure DB-only" in this whole pipeline, since it makes a live OSV.dev call.
``SecurityEngine`` runs second, reading the ``vulnerabilities`` rows that
function just wrote for this run_id (load-bearing order, same "tuple order
is execution order" rule every other multi-engine stage follows) alongside
``secret_hits`` (Facts, written by the earlier "secrets" FACT stage).
``run_ingestion_job`` marks THIS stage ``optional=True`` when calling
``stage()`` -- a total OSV outage fails only this one stage, never the
whole run (app/jobs/stages.py::stage's ``optional`` parameter)."""
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
  07), RiskEngine must run FIRST -- HygieneEngine UPDATEs the
  ``file_metrics`` rows RiskEngine inserts for this run_id (never inserts
  its own; the unique constraint on (analysis_run_id, path_id) would reject
  a second insert).
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
  actually reads the other's output). **TimelineEngine (session 13) runs
  THIRD, after GlossaryEngine and before HealthEngine** -- it needs nothing
  from either (it reads only Facts -- ``commits``/``files`` -- via its own
  single accumulation pass, see app/engines/timeline.py), so its exact slot
  here is a placement choice, not a dependency; it was inserted at the
  position the session 13 prompt specified rather than appended to the end,
  since a later session reading this list top-to-bottom should see the same
  order the prompt itself describes. HealthEngine runs FOURTH, UNCHANGED
  from its pre-session-06 behavior (needs Risk's file_metrics plus
  Architecture's cycles and Overlay's hidden-dependency count -- see its own
  docstring). **PassportEngine runs FIFTH, strictly after HealthEngine, in
  the SAME stage** -- this is the one new load-bearing order dependency
  session 06 introduces: PassportEngine's ``data.health`` embeds the
  ``health`` row HealthEngine writes earlier in this same stage, and the
  onboarding-difficulty formula's inputs are otherwise all already-computed
  by that point. Reordering PassportEngine ahead of HealthEngine within this
  tuple would make it read a row that doesn't exist yet for this run_id.
- "security" (session 10) needs nothing from an earlier INSIGHT stage --
  ``fetch_and_persist_vulnerabilities`` reads only ``dependencies_declared``
  (Facts) and ``SecurityEngine`` reads only ``secret_hits`` (Facts) plus
  ``vulnerabilities`` (written earlier in this SAME stage, by the callable
  immediately before it in the tuple). It's placed here, second-to-last,
  purely to hide its network latency behind progressive reveal -- every
  other tab has already resolved by the time a user would notice this one
  still working.
- "rank" needs every other engine's findings already written for this
  run_id -- which is why it must be LAST, after "security" too.

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
def stage(
    run_id: uuid.UUID, name: str, session: Session, *, optional: bool = False
) -> Iterator[dict[str, Any]]:
    """Marks the ``analysis_stages`` row for ``(run_id, name)`` running ->
    done/failed, COMMITTING at each transition -- the commit-per-stage is
    the whole point of progressive reveal (Part B of the phase spec); never
    batch these into one transaction at the end.

    Yields a mutable ``dict`` the caller fills in as the stage's summary
    (counts, flags, ...); on success it's stored verbatim as the row's
    ``summary`` JSONB.

    On exception, the stage row is ALWAYS marked failed (with the
    exception's message) and committed. What happens to the OWNING
    ``analysis_runs`` row, and whether the exception re-raises, depends on
    ``optional`` (session 10, Part E):

    - **``optional=False`` (default, every stage before session 10)** --
      unchanged behavior: the ``analysis_runs`` row is ALSO marked failed,
      and the exception re-raises, so ``run_ingestion_job``'s outer handler
      can still do its own cleanup (deleting the clone) and mark the
      ``jobs``/``repos`` rows -- crucially, WITHOUT touching
      ``repos.current_run_id``, so a failed re-analysis never blanks out a
      repo that already had a good run (Part C, step 7).
    - **``optional=True``** -- the run is left alone (NOT marked failed) and
      the exception is SWALLOWED here, not re-raised: the caller's loop over
      ``INSIGHT_STAGES`` continues to the next stage as if this one had
      simply finished. This exists because a third-party API outage (the
      "security" stage's OSV.dev lookup) must never fail a whole analysis --
      it's the mechanism session 11's "two working sections, one errored"
      security page depends on: the run still reaches ``ready``, and the
      failed stage's own row (status + ``error``) is exactly what a later
      session's UI reads to show that one section as errored rather than
      pending forever or silently empty.
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

        if not optional:
            run = session.get(AnalysisRun, run_id)
            if run is not None:
                run.status = AnalysisRunStatus.failed
                run.error = str(exc)
                run.finished_at = datetime.now(UTC)

        session.commit()

        if not optional:
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
