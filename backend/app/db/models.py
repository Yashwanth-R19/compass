import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def bigint_pk() -> Mapped[int]:
    """BIGINT identity primary key -- used on every high-volume, repo-scoped
    table (repo_paths, commits, files, coupling, dependencies, findings,
    file_metrics). Left off repos/jobs/health/baselines: those are
    low-volume, and repos.id/jobs.id are exposed in URLs, where a UUID is
    correct (Phase 1 schema diet, CLAUDE.md)."""
    return mapped_column(BigInteger, Identity(), primary_key=True)


class RepoStatus(str, enum.Enum):
    pending = "pending"
    mining = "mining"
    analyzing = "analyzing"
    ready = "ready"
    failed = "failed"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class Severity(str, enum.Enum):
    low = "low"
    med = "med"
    high = "high"


class AnalysisRunStatus(str, enum.Enum):
    running = "running"
    ready = "ready"
    failed = "failed"
    superseded = "superseded"


class StageStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[uuid.UUID] = uuid_pk()
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[RepoStatus] = mapped_column(
        SAEnum(RepoStatus, name="repo_status"), nullable=False, default=RepoStatus.pending
    )
    commit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Facts/Insight split (Phase 02, CLAUDE.md). head_sha is the commit the
    # currently-persisted Facts tables (repo_paths/commits/files/dependencies)
    # were mined from -- compared against a fresh `git ls-remote` on every
    # re-analysis to decide whether cloning/mining can be skipped entirely.
    # current_run_id is the live analysis_runs row the API/frontend read;
    # ON DELETE SET NULL (not CASCADE) because a run being pruned must never
    # cascade into deleting the repo itself.
    head_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )


class AnalysisRun(Base):
    """One row per analysis attempt for a repo -- the Insight layer's version
    key (CLAUDE.md, Facts/Insight split). `coupling`/`file_metrics`/
    `findings`/`health` all carry `analysis_run_id` and are never overwritten
    in place; a re-analysis creates a NEW run rather than replacing the old
    one, which is what makes old runs diffable (Phase 17 A/B compare) and
    prunable (Phase 21 LRU eviction) independently of the Facts tables.
    `engine_version` exists so a future formula change can be told apart from
    an old run computed by different code, without needing to re-run
    anything to find out.
    """

    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_repo_id_started_at", "repo_id", "started_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AnalysisRunStatus] = mapped_column(
        SAEnum(AnalysisRunStatus, name="analysis_run_status"),
        nullable=False,
        default=AnalysisRunStatus.running,
    )
    head_sha: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AnalysisStage(Base):
    """One row per (run, stage-name), pre-created as `pending` for every
    stage in `app/jobs/stages.py`'s canonical list before any work starts --
    so the very first `/repos/{id}/status` poll can render the full stage
    list with skeletons instead of the frontend guessing what's coming.
    `summary` is a small JSONB teaser (e.g. {"commits": 4182}) the UI shows
    the instant a stage lands, not a substitute for the real result tables.
    """

    __tablename__ = "analysis_stages"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_analysis_stages_run_id_name"),)

    id: Mapped[int] = bigint_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[StageStatus] = mapped_column(
        SAEnum(StageStatus, name="stage_status"), nullable=False, default=StageStatus.pending
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class RepoPath(Base):
    """Path-interning table (Phase 1 schema diet): every distinct file path
    in a repo is stored here once and referenced by integer id everywhere
    else -- commits.changed_path_ids, files.path_id,
    coupling.path_a_id/path_b_id, dependencies.from_path_id/to_path_id,
    findings.path_id, file_metrics.path_id. Paths are long strings repeated
    tens of thousands of times across a repo's history; interning them is
    where most of the storage savings come from.

    UNLIKE the other Facts tables (commits/files/dependencies), this table is
    APPEND-ONLY across analysis runs -- app/db/wipe.py's wipe_facts() never
    deletes from it, and persist.py interns only genuinely-new paths on a
    re-run rather than wiping and reassigning ids. This is load-bearing for
    the Facts/Insight split (Phase 02, CLAUDE.md): every Insight row
    (coupling, findings, file_metrics) references a path by this table's
    integer id, and those Insight rows must keep working for OLD analysis
    runs even after the repo gets new commits and its Facts get replaced. If
    repo_paths were wiped-and-reinserted like the other Facts tables, every
    id would change and ON DELETE CASCADE would silently destroy every prior
    run's Insight data the moment a repo was re-analyzed -- exactly the
    "old runs stay diffable/prunable" guarantee this split exists to
    provide (COMPASS_PLAN.md sec 4). A path that no longer exists in the
    current tree simply stops being referenced by current-run Insight rows;
    it is not deleted, since deleting it would require unpicking exactly the
    same cross-run FK problem.
    """

    __tablename__ = "repo_paths"
    __table_args__ = (UniqueConstraint("repo_id", "path", name="uq_repo_paths_repo_id_path"),)

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)


class Commit(Base):
    """``changed_path_ids``/``added_lines``/``deleted_lines`` are three
    parallel arrays: index i in each refers to the same file change in this
    commit -- changed_path_ids[i] is a repo_paths.id, and
    added_lines[i]/deleted_lines[i] are that file's added/deleted line
    counts in this commit. Replaces the old commit_files join table (Phase 1
    schema diet): CouplingEngine reads changed_path_ids directly, no join.
    """

    __tablename__ = "commits"
    __table_args__ = (Index("ix_commits_repo_id_sha", "repo_id", "sha"),)

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sha: Mapped[str] = mapped_column(String, nullable=False, index=True)
    author_name: Mapped[str] = mapped_column(String, nullable=False)
    author_email: Mapped[str] = mapped_column(String, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_fix: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_revert: Mapped[bool] = mapped_column(default=False, nullable=False)
    files_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    insertions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_path_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    added_lines: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    deleted_lines: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_repo_id_path", "repo_id", "path"),
        Index("ix_files_repo_id_path_id", "repo_id", "path_id"),
    )

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False, default="other")
    current_loc: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complexity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    churn_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    commit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)


class FileMetrics(Base):
    """Insight (Phase 02): one row per (analysis_run_id, path_id), NOT
    per file_id. Keyed by path_id rather than the Facts-layer files.id
    deliberately -- files rows get wiped-and-reinserted with fresh ids
    whenever Facts are replaced, and file_metrics must survive that for
    OLDER runs the same way coupling/findings do (see RepoPath's docstring).
    `repo_id` is denormalized here (derivable via path_id -> repo_paths, but
    stored directly, same as coupling/dependencies/findings) so repo-scoped
    reads don't need an extra join.
    """

    __tablename__ = "file_metrics"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "path_id", name="uq_file_metrics_run_id_path_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    hotspot_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Coupling(Base):
    """Insight (Phase 02): `analysis_run_id` versions this table -- a repo
    can have many rows for the same (path_a_id, path_b_id) pair across
    different runs. Every reader (CouplingEngine's own writes, the coupling
    API, OverlayEngine, RiskEngine's max-coupling-by-path, HealthEngine) MUST
    filter by analysis_run_id, not just repo_id, or it mixes pairs from
    unrelated runs."""

    __tablename__ = "coupling"
    __table_args__ = (
        Index("ix_coupling_repo_id_degree", "repo_id", "coupling_degree"),
        Index("ix_coupling_run_id", "analysis_run_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_a_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    path_b_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    shared_revs: Mapped[int] = mapped_column(Integer, nullable=False)
    coupling_degree: Mapped[float] = mapped_column(Float, nullable=False)
    avg_revs: Mapped[float] = mapped_column(Float, nullable=False)


class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    to_path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    dep_type: Mapped[str] = mapped_column(String, nullable=False)


class Finding(Base):
    """Insight (Phase 02): `analysis_run_id` versions this table -- every
    reader (FindingsRankEngine's own rank pass, the /findings API) MUST
    filter by analysis_run_id, not just repo_id, or it ranks/returns findings
    mixed across unrelated runs."""

    __tablename__ = "findings"

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="finding_severity"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    path_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=True
    )
    evidence_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status"), nullable=False, default=JobStatus.queued
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Health(Base):
    """Composite per-RUN health score (app/engines/health.py). Insight
    (Phase 02): one row per analysis_run_id (unique constraint moved off
    repo_id, which is now one-to-many across a repo's run history), inserted
    once by HealthEngine each run -- never updated in place, consistent with
    every other Insight table."""

    __tablename__ = "health"

    id: Mapped[uuid.UUID] = uuid_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    high_risk_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    cycle_count: Mapped[int] = mapped_column(Integer, nullable=False)
    hidden_dependency_count: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Baseline(Base):
    """Corpus percentile baselines. Empty until Release C's CorpusBaseline lands."""

    __tablename__ = "baselines"

    id: Mapped[uuid.UUID] = uuid_pk()
    metric: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)
    size_bucket: Mapped[str] = mapped_column(String, nullable=False)
    p10: Mapped[float] = mapped_column(Float, nullable=False)
    p25: Mapped[float] = mapped_column(Float, nullable=False)
    p50: Mapped[float] = mapped_column(Float, nullable=False)
    p75: Mapped[float] = mapped_column(Float, nullable=False)
    p90: Mapped[float] = mapped_column(Float, nullable=False)
