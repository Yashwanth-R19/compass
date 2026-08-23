import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisRun,
    Commit,
    Coupling,
    Dependency,
    File,
    FileMetrics,
    Finding,
    Health,
    RepoManifest,
    Symbol,
)


def wipe_facts(repo_id: uuid.UUID, session: Session) -> None:
    """Delete the Facts-layer rows that get rebuilt whenever a repo's
    head_sha changes: dependencies, symbols, repo_manifests, files, commits
    (FK-safe order -- dependencies/symbols/repo_manifests/files all FK into
    repo_paths, commits doesn't FK it at all). Called only when the miner is
    about to re-run, never on every re-analysis (Facts/Insight split, Phase
    02, CLAUDE.md).

    Deliberately does NOT delete ``repo_paths``. Unlike the rest of the
    Facts layer, repo_paths is append-only across a repo's whole lifetime --
    see its docstring in app/db/models.py. Insight rows (coupling.path_a_id/
    path_b_id, file_metrics.path_id, findings.path_id) reference it across
    every analysis run, including runs older than the one currently being
    computed; wiping it here would cascade-delete every prior run's Insight
    data the moment this repo got new commits, which is exactly the failure
    the Facts/Insight split exists to prevent (COMPASS_PLAN.md sec 4).

    Caller owns the transaction: this function only issues deletes, it does
    not commit. Wiping an already-empty repo_id (first-ever ingestion) is a
    harmless no-op.
    """
    session.execute(delete(Dependency).where(Dependency.repo_id == repo_id))
    session.execute(delete(Symbol).where(Symbol.repo_id == repo_id))
    session.execute(delete(RepoManifest).where(RepoManifest.repo_id == repo_id))
    session.execute(delete(File).where(File.repo_id == repo_id))
    session.execute(delete(Commit).where(Commit.repo_id == repo_id))


def prune_run(run_id: uuid.UUID, session: Session) -> None:
    """Delete every Insight row belonging to a single analysis run, then the
    run row itself (analysis_stages cascades via its FK to analysis_runs).

    Not called anywhere yet -- Phase 21 wires this to LRU eviction -- but
    implemented and tested now per the Phase 02 spec. Safe to call on any
    run, including ``repos.current_run_id`` (which will fall back to NULL via
    ON DELETE SET NULL); callers doing real eviction should of course never
    prune the current run.

    Insight tables only ever reference Facts tables (repo_paths), never each
    other, so the deletion order among them doesn't matter. Caller owns the
    transaction, same as wipe_facts.
    """
    session.execute(delete(Coupling).where(Coupling.analysis_run_id == run_id))
    session.execute(delete(FileMetrics).where(FileMetrics.analysis_run_id == run_id))
    session.execute(delete(Finding).where(Finding.analysis_run_id == run_id))
    session.execute(delete(Health).where(Health.analysis_run_id == run_id))
    session.execute(delete(AnalysisRun).where(AnalysisRun.id == run_id))
