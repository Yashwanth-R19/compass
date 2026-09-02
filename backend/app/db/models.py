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


CURRENT_ENGINE_VERSION = 2
"""Session 07 (Risk v2): bumped from 1 -- RiskEngine now feeds
``files.churn_weighted`` (recency-decayed) into the locked formula's
churn*complexity term in place of ``churn_total``, a MEASUREMENT change the
locked formula itself explicitly permits (master-context.md sec 8.1 / §3:
"you may improve how an input is measured"). This constant is what
``AnalysisRun.engine_version`` defaults new rows to; a run created before
this session has ``engine_version=1`` and remains readable -- nothing reads
this column to gate behavior, it exists purely so an old run's numbers can
be told apart from a new one's."""


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
    engine_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=CURRENT_ENGINE_VERSION
    )
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
    # Session 07: a graded successor to the coarse `is_fix` regex flag
    # (app/ingestion/persist.py::compute_fix_confidence) -- 1.0 references an
    # issue number AND matches the fix pattern, 0.7 matches the fix pattern
    # alone, 0.3 matches only a weak word like "close"/"closes" (which
    # commonly means "closes #123 [a feature]", not a bug fix), 0.0
    # otherwise. `is_fix` itself is kept as-is for backward compatibility --
    # this is an additional signal, not a replacement.
    fix_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
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
    # Session 07 (Risk v2): computed once by app/ingestion/miner.py during
    # mining (a pure function of this file's own touches across the mined
    # commit history -- Facts, not a per-run Insight value) and persisted
    # here alongside churn_total, which is kept unchanged for comparison.
    # churn_recent_365d is the SUM of added+deleted lines across touches
    # within 365 days of the REPOSITORY's own last commit (a hard window,
    # not decayed). churn_weighted applies exponential decay with a 365-day
    # half-life relative to that same reference point (weight = 0.5 **
    # (age_days / 365)) -- see miner.py's docstring for why "the repo's last
    # commit", never wall-clock, is the correct reference point (same rule
    # app/analysis/staleness.py already established for contributors).
    # RiskEngine feeds churn_weighted into the locked formula's
    # churn*complexity term in place of churn_total (CLAUDE.md "Risk v2").
    churn_recent_365d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    churn_weighted: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


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
    # Session 07: commit-hygiene columns (app/engines/hygiene.py::HygieneEngine),
    # written by an UPDATE against the row RiskEngine already inserted for
    # this (analysis_run_id, path_id) -- HygieneEngine runs immediately after
    # RiskEngine in the same "risk" stage and never re-inserts (the unique
    # constraint on (analysis_run_id, path_id) would reject a second insert
    # anyway). All nullable: a row exists for every scored file the moment
    # RiskEngine writes it, before HygieneEngine has had a chance to fill
    # these in, and there is no meaningful non-null default for "not
    # computed yet" here the way there was for is_test/import_kind (session
    # 03's server_default dance) -- see Known Hazard #2 in that session's
    # plan prompt.
    instability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    revert_cycle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oversized_commit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fixup_commit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Session 07: test-gap columns (app/engines/test_gaps.py::TestGapEngine),
    # same UPDATE-after-RiskEngine-insert pattern as the hygiene columns
    # above -- TestGapEngine runs last in the "risk" stage, after
    # HygieneEngine. test_classification is one of "no_test"/"stale_test"/
    # "tracked" (null only for a file TestGapEngine never scored, e.g. a
    # test file itself). mapped_test_path_ids is the union of both mapping
    # methods (naming convention + structural import edge) -- see that
    # module's docstring.
    test_classification: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_cochange_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    mapped_test_path_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger), nullable=True)


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


class Subsystem(Base):
    """Insight (session 04): one Louvain-detected community from
    ``app/engines/subsystems.py::SubsystemEngine``, one row per
    ``analysis_run_id`` per community (post merge-small/cap-at-12
    post-processing -- see that module). ``label_source`` is one of
    "path_prefix"/"identifiers"/"fallback" so the UI can be honest about how
    confident the generated name is, never presenting a guessed label as a
    verified one. ``cohesion`` is ``internal_edges / (internal_edges +
    external_edges)``, 0.0 for a subsystem with no edges at all (an isolated
    singleton). ``rank`` orders by ``file_count`` desc, stable (ties broken
    by the same sorted-community-list order Louvain post-processing already
    established -- see SubsystemEngine's determinism discipline).
    """

    __tablename__ = "subsystems"
    __table_args__ = (
        Index("ix_subsystems_analysis_run_id", "analysis_run_id"),
        Index("ix_subsystems_repo_id", "repo_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    label_source: Mapped[str] = mapped_column(Text, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_loc: Mapped[int] = mapped_column(Integer, nullable=False)
    internal_edges: Mapped[int] = mapped_column(Integer, nullable=False)
    external_edges: Mapped[int] = mapped_column(Integer, nullable=False)
    cohesion: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class SubsystemMember(Base):
    """Insight (session 04): one (subsystem, file) membership row.
    ``centrality`` is that file's PageRank score across the WHOLE repo graph
    (computed once by ``SubsystemEngine``, session 06/07 read it from here
    rather than ever recomputing PageRank themselves -- see that engine's
    docstring). ``path_id`` references the permanent ``repo_paths.id``, not a
    Facts-layer ``files.id`` (same reasoning as every other per-file Insight
    column, see ``FileMetrics``'s docstring)."""

    __tablename__ = "subsystem_members"
    __table_args__ = (
        UniqueConstraint(
            "subsystem_id", "path_id", name="uq_subsystem_members_subsystem_id_path_id"
        ),
    )

    id: Mapped[int] = bigint_pk()
    subsystem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subsystems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    centrality: Mapped[float] = mapped_column(Float, nullable=False)


class EntryPoint(Base):
    """Insight (session 04): one detected entry point
    (``app/engines/entrypoints.py::EntryPointEngine``). ``kind`` is one of
    "cli"/"web_server"/"ui_root"/"test_root"/"build"/"graph_inferred".
    ``evidence`` is a short, literal statement of the rule that fired (e.g.
    "package.json scripts.dev references this file") -- NEVER a generated
    sentence describing the file itself; see that engine's docstring for the
    full detection-rule table."""

    __tablename__ = "entry_points"
    __table_args__ = (
        Index("ix_entry_points_analysis_run_id", "analysis_run_id"),
        Index("ix_entry_points_repo_id", "repo_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class ModuleCoupling(Base):
    """Insight (session 04): the LOCKED coupling formula
    (``coupling_degree = shared_revs / min(revs(A), revs(B))``, identical to
    file-level ``Coupling``) computed at coarser granularity -- see
    ``app/engines/module_coupling.py`` for why this MUST be computed directly
    from commit changesets at module grain, never aggregated from file-pair
    rows. ``granularity`` is "directory" or "subsystem"; ``module_a``/
    ``module_b`` are always labels (directories aren't interned in
    ``repo_paths``, and a uniform label column lets both granularities share
    one table shape). ``subsystem_a_id``/``subsystem_b_id`` are populated
    only when ``granularity='subsystem'`` -- nullable FKs, not enforced
    against a CHECK constraint, since the engine itself is the only writer
    and always sets both-or-neither per row.
    """

    __tablename__ = "module_coupling"
    __table_args__ = (
        Index(
            "ix_module_coupling_run_id_granularity_degree",
            "analysis_run_id",
            "granularity",
            "coupling_degree",
        ),
        Index("ix_module_coupling_repo_id", "repo_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    granularity: Mapped[str] = mapped_column(Text, nullable=False)
    module_a: Mapped[str] = mapped_column(Text, nullable=False)
    module_b: Mapped[str] = mapped_column(Text, nullable=False)
    subsystem_a_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subsystems.id", ondelete="CASCADE"), nullable=True
    )
    subsystem_b_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subsystems.id", ondelete="CASCADE"), nullable=True
    )
    shared_revs: Mapped[int] = mapped_column(Integer, nullable=False)
    coupling_degree: Mapped[float] = mapped_column(Float, nullable=False)
    avg_revs: Mapped[float] = mapped_column(Float, nullable=False)


class Contributor(Base):
    """Insight (session 05): one row per author identity resolved by
    ``app/analysis/identities.py::resolve_identities`` -- a single real
    person (or bot) may have committed under several (name, email) pairs;
    every pair merged into this identity is recorded verbatim in
    ``aliases`` (a list of ``{"name": ..., "email": ...}`` objects) so the
    merge is auditable, not just asserted. ``canonical_email``/every alias
    email is the RAW value -- masked only at the API boundary
    (``app/analysis/identities.py::mask_email``); no endpoint ever returns
    an unmasked one (plan/RULES.md sec 11.2).

    Bots (``github-actions[bot]``, ``dependabot[bot]``, anything ending
    ``[bot]``) get a row here too, with ``is_bot=True`` -- excluded from
    ``file_expertise``/``truck_factor`` entirely, but their
    ``commit_count``/lines are still recorded here so "N% of commits are
    from dependabot[bot]" is directly computable from this table, per
    session 05 Part A.

    ``rank`` orders by ``commit_count`` desc (ties broken by
    ``canonical_name`` asc) -- ACTIVITY, never a "contribution score" or a
    sort by lines changed (plan/RULES.md sec 11.3 / session 05 Known
    Hazard #8).
    """

    __tablename__ = "contributors"
    __table_args__ = (
        Index("ix_contributors_analysis_run_id", "analysis_run_id"),
        Index("ix_contributors_repo_id", "repo_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_email: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False)
    commit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False)
    lines_deleted: Mapped[int] = mapped_column(Integer, nullable=False)
    first_commit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_commit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # Session 05: staleness is measured against the REPOSITORY's own most
    # recent commit, never datetime.now() -- see
    # app/analysis/staleness.py::is_stale_relative_to_repo. An archived
    # repo whose whole team was active up until the last commit has nobody
    # stale, even though every timestamp is old by the wall-clock.
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class FileExpertise(Base):
    """Insight (session 05): one row per (file, contributor) Degree-of-
    Authorship result, ``app/engines/expertise.py``. Only the top
    ``MAX_EXPERTS_PER_FILE`` (5) contributors per file are stored -- at
    5,000 files x 50 contributors this table would otherwise dominate the
    storage budget. Ranking and ``doa_normalized`` are both computed over
    the FULL contributor set for that file BEFORE this truncation, never
    after (session 05 Known Hazard #5: truncating first would produce
    ``doa_normalized`` values that never reach 1.0).

    ``path_id`` references the permanent ``repo_paths.id``, not a
    Facts-layer ``files.id`` -- same reasoning as every other per-file
    Insight column (see ``FileMetrics``'s docstring). ``contributor_id`` is
    only ever a NON-bot contributor -- bots are excluded from expertise
    entirely (session 05 Part A/C).
    """

    __tablename__ = "file_expertise"
    __table_args__ = (Index("ix_file_expertise_run_id_path_id", "analysis_run_id", "path_id"),)

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    contributor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contributors.id", ondelete="CASCADE"), nullable=False
    )
    doa: Mapped[float] = mapped_column(Float, nullable=False)
    doa_normalized: Mapped[float] = mapped_column(Float, nullable=False)
    is_expert: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changes: Mapped[int] = mapped_column(Integer, nullable=False)
    last_touched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TruckFactor(Base):
    """Insight (session 05): one row per analysis run,
    ``app/engines/truck_factor.py`` -- Avelino's greedy removal algorithm
    over ``file_expertise``. ``removal_order`` (JSONB list of
    ``{contributor_id, name, files_orphaned, cumulative_orphan_ratio}``) is
    what makes the number explainable rather than a bare integer: "if Alice
    leaves, 34% of files lose their expert; if Bob also leaves, 51%."
    ``note`` is set only for the degenerate cases (a single contributor,
    zero files with any expert) -- null in the normal case.

    This measures the PROJECT's knowledge-distribution risk, never an
    individual's importance (plan/RULES.md sec 11.4) -- the API attaches a
    fixed interpretation string alongside this row's data on every read,
    see ``app/api/analysis.py::KNOWLEDGE_INTERPRETATION_NOTE``, rather than
    storing that framing redundantly on every row.

    One row per run, like ``Health`` -- uses a UUID PK (not the bigint
    identity PK the two higher-volume tables above use), matching
    ``Health``'s existing one-row-per-run convention.
    """

    __tablename__ = "truck_factor"

    id: Mapped[uuid.UUID] = uuid_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    removal_order: Mapped[list] = mapped_column(JSONB, nullable=False)
    total_files_considered: Mapped[int] = mapped_column(Integer, nullable=False)
    orphaned_file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class TourStop(Base):
    """Insight (session 06): one stop in ``app/engines/tour.py``'s computed
    guided reading order for a run. ``position`` is the 1-based reading
    order (unique per run); ``path_id`` references the permanent
    ``repo_paths.id``, same reasoning as every other per-file Insight column
    (see ``FileMetrics``'s docstring). ``reason_code`` is the machine-readable
    PRIMARY justification this stop was selected (one of "documentation",
    "entry_point", "subsystem_anchor", "high_centrality", "widely_depended_on",
    "hotspot" -- see TourEngine's module docstring for the priority order used
    when a file qualifies under more than one rule). ``reason_detail`` is the
    JSONB backing those numbers (in_degree/out_degree/pagerank/loc/complexity/
    risk_score/risk_confidence/subsystem/top_expert/last_touched_at, PLUS a
    nested ``"reasons"`` object recording every rule that fired for this
    stop, not just the primary one, so the UI can show secondary
    justifications) -- TourEngine guarantees this is never an empty object.
    ``subsystem_id`` is the subsystem this stop's file belongs to (nullable
    only because a run could in principle have zero subsystems, e.g. a
    zero-file repo); ``ON DELETE CASCADE`` since a pruned subsystem set
    means this stop's subsystem context no longer exists either.
    """

    __tablename__ = "tour_stops"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "position", name="uq_tour_stops_run_id_position"),
        Index("ix_tour_stops_repo_id", "repo_id"),
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
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    subsystem_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subsystems.id", ondelete="CASCADE"), nullable=True
    )


class GlossaryTerm(Base):
    """Insight (session 06): one ranked domain-vocabulary term from
    ``app/engines/glossary.py::GlossaryEngine``, mined from ``symbols.name``
    values and file stems only -- never file contents (engines have no
    filesystem access). ``score`` is the HEURISTIC
    ``log(1 + occurrences) * (1 + subsystem_spread / total_subsystems)``
    formula (see that engine's module docstring); ``subsystem_spread`` is how
    many distinct subsystems contain an occurrence of this term.
    ``defining_path_ids`` is up to 5 ``repo_paths.id`` values -- files
    containing a SYMBOL (not just a filename) whose tokenized name includes
    this term, the "go read this" links a glossary entry is useless without.
    ``rank`` is 0-indexed, score desc, ties broken by term asc (determinism).
    """

    __tablename__ = "glossary_terms"
    __table_args__ = (
        Index("ix_glossary_terms_analysis_run_id", "analysis_run_id"),
        Index("ix_glossary_terms_repo_id", "repo_id"),
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
    term: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    subsystem_spread: Mapped[int] = mapped_column(Integer, nullable=False)
    defining_path_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class RepoPassport(Base):
    """Insight (session 06): one row per run, ``app/engines/passport.py::
    PassportEngine`` -- pure aggregation over every other engine's output for
    this run (must run after HealthEngine, in the same "onboarding" stage,
    since ``data`` embeds the health row -- see app/jobs/stages.py). ``data``
    is validated against ``app/engines/passport.py::RepoPassportData``
    (a Pydantic model) before being stored, never a hand-built dict.
    ``onboarding_difficulty``/``difficulty_breakdown`` are the EXPLICITLY
    HEURISTIC 0-100 composite score and its component breakdown (raw +
    normalized value per component) -- see that engine's module docstring;
    NOT locked by master-context.md, same honesty convention as
    ``HealthEngine``'s composite. Like ``Health``/``TruckFactor``, one row
    per run -- UUID PK, not the bigint identity PK the two higher-volume
    tables above use.
    """

    __tablename__ = "repo_passport"

    id: Mapped[uuid.UUID] = uuid_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    onboarding_difficulty: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)


class HygieneEvent(Base):
    """Insight (session 07): one row per detected commit-hygiene occurrence
    from ``app/engines/hygiene.py::HygieneEngine`` -- EVERY detected event,
    not capped (unlike ``findings``, which caps at
    ``MAX_HYGIENE_FINDINGS=8`` across all kinds; this table is the full,
    unranked evidence log the API's ``/hygiene`` endpoint reads back
    wholesale). ``kind`` is one of "oversized"/"fixup_churn"/"risky_commit".
    ``commit_sha`` is always a single sha even for a "fixup_churn" cluster
    event, which spans several commits -- the FIRST commit in the detected
    sequence (when the cluster began); the full list of shas in the cluster
    lives in ``detail``. ``severity_hint`` mirrors the fixed, HEURISTIC
    per-kind severity HygieneEngine assigns (never above MED, plan/RULES.md
    sec 12/CLAUDE.md) -- a plain string, not the ``Severity`` enum, since an
    event that never becomes a ``findings`` row still needs to convey
    roughly how concerning it is.
    """

    __tablename__ = "hygiene_events"
    __table_args__ = (
        Index("ix_hygiene_events_analysis_run_id", "analysis_run_id"),
        Index("ix_hygiene_events_repo_id", "repo_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    commit_sha: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    severity_hint: Mapped[str] = mapped_column(Text, nullable=False)


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


class SecretHit(Base):
    """Facts (session 10, Part A/B): one detected secret occurrence from
    ``app/security/scanner.py::scan_history``, found scanning the repo's
    FULL commit history diff (including secrets later deleted). Keyed by
    ``repo_id`` only, like every other Facts table -- wiped and fully
    replaced by ``wipe_facts`` whenever ``head_sha`` changes, same as
    ``symbols``/``repo_manifests``.

    **Never carries the raw secret value** -- see the five never-re-leak
    rules in ``app/security/scanner.py``'s module docstring, which this
    table's own column set enforces structurally: ``fingerprint`` (a salted
    SHA-256 -- ``sha256(salt + rule_id + normalized_secret_value)``, salt
    read once from ``app.config.settings``) and ``redacted_preview`` (first
    4 + last 2 characters, fixed-length mask between, ``None`` for anything
    shorter than 12 characters) are the only trace of the value itself; there
    is no column either could leak a raw secret into even by accident.

    ``path_id`` is nullable: a hit's path can legitimately fail to resolve
    against ``repo_paths`` (e.g. a path under an IGNORE_DIRS-pruned
    directory the scanner itself also skips, or the diff's file header being
    ``/dev/null`` for a pure deletion). ``still_in_head`` is computed by a
    SECOND pass over the current working tree (never inferred from "does the
    file still exist" -- a file can survive while the specific secret line
    was removed from it, session 10 Known Hazard #7) and is the single most
    important field on this table: a secret that is ``still_in_head=False``
    is the demo this session exists to build -- deleted from the tree,
    still fully recoverable from public git history.

    Unique on ``(repo_id, fingerprint, commit_sha)`` -- the same physical
    secret string can be matched by the same rule on more than one
    line/file within a single commit; ``app/security/scanner.py::
    persist_secret_hits`` deduplicates to one row per that triple before
    inserting.
    """

    __tablename__ = "secret_hits"
    __table_args__ = (
        UniqueConstraint(
            "repo_id", "fingerprint", "commit_sha", name="uq_secret_hits_repo_fingerprint_commit"
        ),
        Index("ix_secret_hits_repo_id", "repo_id"),
    )

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    path_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=True
    )
    commit_sha: Mapped[str] = mapped_column(Text, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    redacted_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    entropy: Mapped[float | None] = mapped_column(Float, nullable=True)
    still_in_head: Mapped[bool] = mapped_column(Boolean, nullable=False)


class DependencyDeclared(Base):
    """Facts (session 10, Part B/C): one declared dependency parsed from a
    supported manifest (``requirements*.txt``, ``pyproject.toml``
    ``[project.dependencies]``, ``package-lock.json``, ``pom.xml`` -- see
    ``app/ingestion/manifests.py::extract_declared_dependencies``). Keyed by
    ``repo_id`` only -- wiped and fully replaced by ``wipe_facts`` whenever
    ``head_sha`` changes, same as ``symbols``/``repo_manifests``.

    ``ecosystem`` is OSV's own exact, case-sensitive ecosystem name
    (``"PyPI"``, ``"npm"``, or ``"Maven"`` -- session 10 Known Hazard #4).
    ``version`` is nullable: a manifest can declare a version RANGE (e.g.
    ``requests>=2.0`` with no lockfile), which is recorded here for
    completeness but can never be queried against OSV (only an exact,
    resolved version can) -- ``app/engines/security.py::
    load_declared_dependencies`` filters these out before calling OSV.
    ``manifest_path_id`` FKs the permanent ``repo_paths.id`` of the manifest
    file this row was extracted from. ``scope`` is one of "runtime"/"dev"/
    "test", best-effort per format (a lockfile's own ``dev`` flag, a
    requirements filename containing "dev"/"test", a Maven ``<scope>`` tag).
    """

    __tablename__ = "dependencies_declared"
    __table_args__ = (Index("ix_dependencies_declared_repo_id", "repo_id"),)

    id: Mapped[int] = bigint_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ecosystem: Mapped[str] = mapped_column(Text, nullable=False)
    package_name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    manifest_path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repo_paths.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)


class Vulnerability(Base):
    """Insight (session 10, Part B/C): one (declared dependency, OSV
    advisory) match for a run, written by ``app/engines/security.py::
    fetch_and_persist_vulnerabilities`` -- the one INSIGHT-stage step in the
    whole pipeline that touches the network (see that function's docstring
    for why this deliberately isn't an ``Engine``). ``analysis_run_id``
    versions this table like every other Insight table: a re-analysis
    re-queries OSV fresh and writes a new set of rows for the new run,
    leaving older runs' rows untouched.

    ``severity`` is a plain TEXT column (``"low"``/``"med"``/``"high"``/
    ``"unknown"``), NOT the ``Severity`` enum -- OSV data can genuinely carry
    no severity information at all (Part C: "mark it unknown -- do not
    invent a severity"), a fourth value the ``Severity`` enum has no member
    for. ``SecurityEngine`` maps this to the enum only when constructing the
    ``findings`` row. ``aliases`` is OSV's own alias list (CVE ids, GHSA
    ids, ...), JSONB. ``fixed_version`` is nullable: not every advisory has
    a published fix yet.
    """

    __tablename__ = "vulnerabilities"
    __table_args__ = (
        Index("ix_vulnerabilities_analysis_run_id", "analysis_run_id"),
        Index("ix_vulnerabilities_repo_id", "repo_id"),
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
    ecosystem: Mapped[str] = mapped_column(Text, nullable=False)
    package_name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    osv_id: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    cvss_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    fixed_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False)


class OsvCache(Base):
    """A GLOBAL cache, deliberately OUTSIDE both the Facts and Insight
    lifecycles (session 10, Part B) -- never touched by ``wipe_facts`` (it
    isn't repo-scoped at all) and never touched by ``prune_run`` (it isn't
    run-scoped either). An OSV advisory (e.g. ``GHSA-xxxx-yyyy-zzzz``) is
    the same fact regardless of which repository or which analysis run asks
    about it, so it's fetched from OSV.dev once, ever, across every
    repository Compass analyzes, keyed by the advisory id itself
    (``osv_id``, a natural TEXT primary key -- no synthetic id needed).
    ``data`` is the raw OSV vulnerability JSON, verbatim; ``fetched_at`` is
    when it was cached, purely informational (there is no TTL/eviction for
    this table -- a published advisory's own content essentially never
    changes after the fact in a way that would matter here).
    """

    __tablename__ = "osv_cache"

    osv_id: Mapped[str] = mapped_column(Text, primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Narrative(Base):
    """Insight (session 12, Part D): one cached LLM-phrased narrative for a
    run -- ``app/narrative/generate.py`` writes these, lazily, the first
    time ``GET /repos/{id}/narrative`` is asked for a given
    ``(surface, subject_key)``; every later call for the same triple reads
    this row instead of calling a provider again. ``surface`` is one of
    ``"passport"``/``"risk_file"``/``"security"``; ``subject_key`` is the
    file path for ``"risk_file"`` (one surface, many narratives) and left
    unused (empty string, never a raw ``NULL`` -- see the API layer's
    comment on why) for the two whole-run surfaces. ``factpack_hash`` is a
    sha256 of the serialized fact pack that produced ``content`` -- a
    changed fact pack (in practice: this would only happen if the DATA
    itself changed, which for a fixed ``analysis_run_id`` should never
    happen, but the hash is what makes a mismatch a cache-invalidation
    signal rather than silently ever serving stale prose) triggers
    regeneration. ``provider``/``model`` are surfaced by the API for
    transparency -- the UI shows which model phrased a given narrative.

    No ``repo_id`` column: this table is looked up ONLY by
    ``analysis_run_id`` (a run already implies exactly one repo), unlike
    most other Insight tables, which also carry a denormalised ``repo_id``
    for cheap repo-scoped queries that don't apply here -- the session
    prompt's own column list for this table is exhaustive and doesn't
    include one.
    """

    __tablename__ = "narratives"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id", "surface", "subject_key", name="uq_narratives_run_surface_subject"
        ),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    subject_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    factpack_hash: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Snapshot(Base):
    """Insight (session 13, Part C): one row per history-derived point on the
    evolution timeline, ``app/engines/timeline.py::TimelineEngine``.
    ``position`` is the 0-indexed chronological order within this run (unique
    per run); ``commit_index`` is that same point's index into the repo's
    FULL chronologically-sorted commit list (what
    ``app/analysis/snapshots.py::select_snapshot_points`` spaced evenly by).
    ``metrics`` is the whole per-snapshot payload -- file_count,
    churn_to_date, commits_to_date, active_contributors, contributor_shares,
    coupling_pairs_count, top_coupling_pairs, churn_ranked_hotspots (see that
    engine's module docstring for the HONESTY CONSTRAINT this table's
    contents are governed by: every field here is history-derived, nothing
    structural -- no import graph, subsystems, complexity, or cycles, at any
    historical point). Stored as one compact JSONB blob per snapshot rather
    than per-file table copies, since the whole point is a small, fixed
    number of points (HISTORY_SNAPSHOTS = 24) summarizing the WHOLE repo at
    that point, not per-file rows that would multiply by file count.
    """

    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "position", name="uq_snapshots_run_id_position"),
        Index("ix_snapshots_repo_id", "repo_id"),
    )

    id: Mapped[int] = bigint_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_sha: Mapped[str] = mapped_column(Text, nullable=False)
    at_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    commit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
