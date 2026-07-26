import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


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


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (Index("ix_commits_repo_id_sha", "repo_id", "sha"),)

    id: Mapped[uuid.UUID] = uuid_pk()
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


class CommitFile(Base):
    """Per-commit changeset join table. Read by the coupling engine (A3)."""

    __tablename__ = "commit_files"
    __table_args__ = (Index("ix_commit_files_commit_id", "commit_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    commit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commits.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String, nullable=False)


class File(Base):
    __tablename__ = "files"
    __table_args__ = (Index("ix_files_repo_id_path", "repo_id", "path"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
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
    __tablename__ = "file_metrics"

    id: Mapped[uuid.UUID] = uuid_pk()
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    hotspot_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Coupling(Base):
    __tablename__ = "coupling"
    __table_args__ = (Index("ix_coupling_repo_id_degree", "repo_id", "coupling_degree"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_a_path: Mapped[str] = mapped_column(String, nullable=False)
    file_b_path: Mapped[str] = mapped_column(String, nullable=False)
    shared_revs: Mapped[int] = mapped_column(Integer, nullable=False)
    coupling_degree: Mapped[float] = mapped_column(Float, nullable=False)
    avg_revs: Mapped[float] = mapped_column(Float, nullable=False)


class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_path: Mapped[str] = mapped_column(String, nullable=False)
    to_path: Mapped[str] = mapped_column(String, nullable=False)
    dep_type: Mapped[str] = mapped_column(String, nullable=False)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="finding_severity"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
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
    """Composite per-repo health score (app/engines/health.py). One row per
    repo_id, overwritten (delete-then-insert via wipe_repo_data, same as
    every other repo-scoped table) on each re-run rather than updated in
    place, so re-analysis stays a full replace like everything else."""

    __tablename__ = "health"

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repos.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
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
