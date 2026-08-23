import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
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


class User(Base):
    """A Compass account, created/updated on every successful GitHub OAuth
    callback (session 02, Part A/C) -- upserted by ``github_id``, GitHub's
    own stable numeric user id (never the mutable ``github_login``).

    ``access_token_encrypted`` is the user's GitHub access token, Fernet-
    encrypted at rest (app/auth/crypto.py) -- NEVER stored, logged, or
    returned plaintext anywhere (plan/RULES.md sec 10). ``token_scopes`` is
    the space-separated scope string GitHub actually granted (not what was
    requested -- a user can approve a narrower set than requested in some
    GitHub Apps flows, though not for this OAuth App flow in practice; still
    recorded as ground truth rather than assumed). Both are nullable because
    a user who has only ever done the profile-only login (``scope=basic``,
    two-step escalation, CLAUDE.md) has authenticated but never granted repo
    access, and ``DELETE /auth/github/connection`` clears both back to NULL
    without deleting the user row itself (they may log back in).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    github_login: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    token_scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    # Session 02, Part A/D: the user who first successfully submitted this
    # repo (set once, at creation, never reassigned on re-analysis -- see
    # CLAUDE.md's access-control section for why ownership doesn't drift to
    # whoever happens to re-trigger analysis later). ON DELETE SET NULL: a
    # deleted user account must not cascade into deleting repos/analysis
    # data other people may still be able to read (a public repo) or that
    # should simply become unowned (a private repo nobody can reach anymore
    # anyway, since access requires the owner's live token).
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visibility_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    # Session 01: persisted by CouplingEngine from compute_coupling()'s
    # return value -- true when the normal MIN_SHARED_REVS floor produced
    # zero pairs and the engine fell back to FALLBACK_MIN_SHARED_REVS (see
    # app/engines/coupling.py::is_low_confidence). NULL means the coupling
    # stage for this run hasn't completed yet, not "not low confidence" --
    # is_low_confidence() treats NULL as False since there is nothing to be
    # low-confidence about inside the 202 window. Deliberately NOT
    # re-derivable from a commit count; see FALLBACK_MIN_SHARED_REVS's
    # docstring for why.
    coupling_low_confidence: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Session 01: which transport actually ran this job -- "inline"
    # (FastAPI BackgroundTasks), "actions" (dispatched to the GitHub Actions
    # worker), or "inline_fallback" (actions dispatch was attempted but
    # failed, e.g. a GitHub outage, and the job fell back to inline so a
    # GitHub Actions outage never means Compass itself is down). Set by
    # app/jobs/dispatch.py::dispatch_run. NULL for any run created before
    # this column existed.
    worker_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Session 02: best-effort audit of who triggered this specific run.
    # Populated from the authenticated request for inline/inline_fallback
    # runs (the same process has the real user context); left NULL for
    # "actions"-mode runs, since the GitHub Actions dispatch payload
    # deliberately carries only repo_id/run_id and no user id (CLAUDE.md's
    # worker-dispatch section) -- adding one would widen that payload
    # contract just for this optional audit field. Nullable for that reason
    # and because runs created before this column existed have none. ON
    # DELETE SET NULL: a deleted user's past runs stay valid analysis
    # history, just no longer attributable.
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


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
    # Session 03: populated by persist.py's shared test-path classifier
    # (app/ingestion/persist.py::classify_is_test) during persist_facts --
    # one function, reused by session 07's test-gap analysis, so the two
    # never define "is this a test file" differently. See that function's
    # docstring for the exact per-language rules.
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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
    # Session 03: "static" for a normal import/require/import-from edge,
    # "dynamic" for a JS dynamic import(...) call whose string-literal
    # argument resolved to a real file (app/languages/javascript_analyzer.py)
    # -- lets a later session distinguish the two without a migration.
    # Populated as "static" for every edge except that one JS case.
    import_kind: Mapped[str] = mapped_column(String, nullable=False, default="static")


class Symbol(Base):
    """Facts (session 03): one class/function/etc. declaration extracted by
    a ``LanguageAnalyzer.extract_symbols`` during the "structure" stage
    (app/languages/scanner.py) -- feeds session 04's entry-point detection
    and beyond. Keyed by ``repo_id`` only, like every other Facts table --
    wiped and fully replaced by ``wipe_facts`` whenever ``head_sha``
    changes, UNLIKE ``repo_paths``, which stays append-only (see
    ``RepoPath``'s docstring). ``path_id`` references that permanent id, not
    a Facts-layer ``files.id``, so a symbol row is always attributable to a
    real interned path even across a Facts replace.
    """

    __tablename__ = "symbols"
    __table_args__ = (Index("ix_symbols_repo_id_name", "repo_id", "name"),)

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    line: Mapped[int] = mapped_column(Integer, nullable=False)
    exported: Mapped[bool] = mapped_column(Boolean, nullable=False)


class RepoManifest(Base):
    """Facts (session 03): the small set of fields ``app/ingestion/manifests.py``
    extracts from one project manifest file (package.json, pyproject.toml,
    a Dockerfile, a Procfile, pom.xml, build.gradle(.kts), setup.py, a
    requirements*.txt, README*, or LICENSE*) -- NEVER the whole file. ``kind``
    is one of "package_json", "pyproject", "dockerfile", "procfile",
    "pom_xml", "build_gradle", "setup_py", "requirements", "license",
    "readme". ``data`` is JSONB holding only the extracted fields. Facts,
    like ``symbols`` -- wiped and fully replaced by ``wipe_facts`` whenever
    ``head_sha`` changes. Designed to be extensible: session 10 reuses this
    table for dependency manifests rather than inventing a parallel one.
    """

    __tablename__ = "repo_manifests"

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Finding(Base):
    """Insight (Phase 02): `analysis_run_id` versions this table -- every
    reader (FindingsRankEngine's own rank pass, the /findings API) MUST
    filter by analysis_run_id, not just repo_id, or it ranks/returns findings
    mixed across unrelated runs."""

    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_run_id_signature", "analysis_run_id", "signature"),)

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
    # Session 01: stable cross-run identity via app/engines/signature.py::
    # finding_signature -- what session 13's run-to-run diff (appeared /
    # resolved / persisted) matches on instead of fuzzy title comparison.
    # Nullable because findings from before this column existed have none;
    # every finding-emitting engine going forward MUST set it (see
    # CLAUDE.md's finding-signature convention).
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class ShareLink(Base):
    """A share link grants read access to ONE analysis run, not to the
    repository (session 02, Part E/CLAUDE.md) -- ``run_id`` is a FK straight
    to ``analysis_runs.id``, never to ``repos.id``. A later run of the same
    private repository is not exposed by an older share link: a fresh
    re-analysis creates a brand-new ``analysis_runs`` row (Facts/Insight
    split, unchanged by this session), and this table has no row pointing at
    it unless someone explicitly shares that new run too.

    ``ON DELETE CASCADE`` to ``analysis_runs``: pruning a run (Phase 21 LRU
    eviction, not wired up yet) must also invalidate any share link that
    pointed at it -- a dangling share link to a deleted run would be a
    confusing 404 at best.

    ``slug`` is a short random urlsafe string (``secrets.token_urlsafe``),
    unique and indexed -- the only thing ``GET /shared/{slug}`` looks up by.
    ``revoked_at`` is nullable/set-once: a share link is revoked by setting
    it, never by deleting the row (keeping the row lets an old link resolve
    to a clear "revoked" 404 rather than an ambiguous "never existed" one,
    though the API response is the same either way per the session prompt --
    the row is kept for audit purposes).
    """

    __tablename__ = "share_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
