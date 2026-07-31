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
from app.engines.coupling import CouplingEngine
from app.engines.findings import FindingsRankEngine
from app.engines.health import HealthEngine
from app.engines.overlay import OverlayEngine
from app.engines.risk import RiskEngine

StageKind = Literal["fact", "insight"]

EngineCallable = Callable[[uuid.UUID, uuid.UUID, Session], dict[str, Any]]


@dataclass(frozen=True)
class Stage:
    """One entry in the canonical, ordered stage list (Phase 02, CLAUDE.md).

    ``callable`` is only populated for "insight" stages, where every engine
    already shares the uniform ``Engine.run(repo_id, run_id, session) -> dict``
    signature (app/engines/base.py) -- letting the runner drive them
    generically: ``s.callable(repo_id, run_id, session)``. "fact" stages
    (clone/mine/structure/persist_facts) have no such uniform signature --
    each one both consumes and produces different local state (a clone path,
    a MinedRepo, a dependency list) that has to thread through the next
    stage -- so ``run_ingestion_job`` runs their bodies inline instead of
    through this field, and it is left ``None``.
    """

    name: str
    kind: StageKind
    callable: EngineCallable | None = None


FACT_STAGES: tuple[Stage, ...] = (
    Stage("clone", "fact"),
    Stage("mine", "fact"),
    Stage("structure", "fact"),
    Stage("persist_facts", "fact"),
)

INSIGHT_STAGES: tuple[Stage, ...] = (
    Stage("coupling", "insight", CouplingEngine().run),
    Stage("architecture", "insight", ArchEngine().run),
    Stage("overlay", "insight", OverlayEngine().run),
    Stage("risk", "insight", RiskEngine().run),
    Stage("health", "insight", HealthEngine().run),
    Stage("rank", "insight", FindingsRankEngine().run),
)
"""Fixed order, load-bearing (CLAUDE.md "Engines" section): Overlay needs
Coupling+Architecture, Risk needs Coupling's max coupling_degree, Health
needs Risk's file_metrics plus Architecture's cycles and Overlay's
hidden-dependency count, and FindingsRank needs every other engine's
findings already written for this run_id. Do not reorder."""

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
