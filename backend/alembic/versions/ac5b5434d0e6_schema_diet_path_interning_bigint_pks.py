"""schema diet: path interning + bigint identity PKs

Revision ID: ac5b5434d0e6
Revises: 43b7ca24e69c
Create Date: 2026-07-26 00:00:00.000000

Phase 1 (COMPASS_PLAN.md / plan/PHASE_01_miner_and_schema.md): shrinks
storage on the high-volume, repo-scoped tables.

  * New ``repo_paths`` interning table -- every distinct file path in a repo
    is stored once and referenced by integer id everywhere else.
  * ``commit_files`` is dropped entirely, replaced by three parallel
    INTEGER[] columns on ``commits`` (changed_path_ids/added_lines/
    deleted_lines) that CouplingEngine reads with no join at all.
  * ``commits``, ``files``, ``coupling``, ``dependencies``, ``findings``,
    ``file_metrics`` move from UUID primary keys to BIGINT identity, and
    their path-string columns (file_a_path/file_b_path, from_path/to_path,
    file_path) become integer FKs into ``repo_paths``
    (``files.path`` is the one exception, kept alongside ``files.path_id``
    since it's still read directly in many places).

This is a DESTRUCTIVE migration -- it drops commit_files outright and
recreates commits/files/coupling/dependencies/findings/file_metrics from
scratch rather than attempting in-place ``ALTER COLUMN ... TYPE`` surgery on
a UUID column that has no sane cast to BIGINT. That is acceptable because
Compass re-ingestion is a full delete-then-reinsert by design (see
wipe_repo_data / CLAUDE.md "Idempotent re-ingestion") and no production data
exists yet -- any repo affected by this migration just needs to be
re-ingested afterward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac5b5434d0e6"
down_revision: str | None = "43b7ca24e69c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- Drop tables being replaced, child-of-a-FK first ----
    op.drop_index("ix_commit_files_commit_id", table_name="commit_files")
    op.drop_table("commit_files")

    op.drop_table("file_metrics")

    op.drop_index("ix_coupling_repo_id_degree", table_name="coupling")
    op.drop_index(op.f("ix_coupling_repo_id"), table_name="coupling")
    op.drop_table("coupling")

    op.drop_index(op.f("ix_dependencies_repo_id"), table_name="dependencies")
    op.drop_table("dependencies")

    op.drop_index(op.f("ix_findings_repo_id"), table_name="findings")
    op.drop_table("findings")

    op.drop_index("ix_files_repo_id_path", table_name="files")
    op.drop_index(op.f("ix_files_repo_id"), table_name="files")
    op.drop_table("files")

    op.drop_index(op.f("ix_commits_sha"), table_name="commits")
    op.drop_index("ix_commits_repo_id_sha", table_name="commits")
    op.drop_index(op.f("ix_commits_repo_id"), table_name="commits")
    op.drop_table("commits")

    # ---- repo_paths: the interning table everything else now references ----
    op.create_table(
        "repo_paths",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "path", name="uq_repo_paths_repo_id_path"),
    )
    op.create_index(op.f("ix_repo_paths_repo_id"), "repo_paths", ["repo_id"], unique=False)

    # ---- commits: BIGINT identity PK + three parallel path/line arrays ----
    op.create_table(
        "commits",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("sha", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=False),
        sa.Column("author_email", sa.String(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_fix", sa.Boolean(), nullable=False),
        sa.Column("is_revert", sa.Boolean(), nullable=False),
        sa.Column("files_changed", sa.Integer(), nullable=False),
        sa.Column("insertions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column(
            "changed_path_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column(
            "added_lines",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column(
            "deleted_lines",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commits_repo_id"), "commits", ["repo_id"], unique=False)
    op.create_index("ix_commits_repo_id_sha", "commits", ["repo_id", "sha"], unique=False)
    op.create_index(op.f("ix_commits_sha"), "commits", ["sha"], unique=False)

    # ---- files: BIGINT identity PK + path_id FK (path string kept too) ----
    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("path_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("current_loc", sa.Integer(), nullable=False),
        sa.Column("complexity", sa.Float(), nullable=False),
        sa.Column("churn_total", sa.Integer(), nullable=False),
        sa.Column("commit_count", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["path_id"], ["repo_paths.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_files_repo_id"), "files", ["repo_id"], unique=False)
    op.create_index("ix_files_repo_id_path", "files", ["repo_id", "path"], unique=False)
    op.create_index("ix_files_repo_id_path_id", "files", ["repo_id", "path_id"], unique=False)

    # ---- coupling: BIGINT identity PK + path_a_id/path_b_id FKs ----
    op.create_table(
        "coupling",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("path_a_id", sa.BigInteger(), nullable=False),
        sa.Column("path_b_id", sa.BigInteger(), nullable=False),
        sa.Column("shared_revs", sa.Integer(), nullable=False),
        sa.Column("coupling_degree", sa.Float(), nullable=False),
        sa.Column("avg_revs", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["path_a_id"], ["repo_paths.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["path_b_id"], ["repo_paths.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_coupling_repo_id"), "coupling", ["repo_id"], unique=False)
    op.create_index(
        "ix_coupling_repo_id_degree", "coupling", ["repo_id", "coupling_degree"], unique=False
    )

    # ---- dependencies: BIGINT identity PK + from_path_id/to_path_id FKs ----
    op.create_table(
        "dependencies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("from_path_id", sa.BigInteger(), nullable=False),
        sa.Column("to_path_id", sa.BigInteger(), nullable=False),
        sa.Column("dep_type", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_path_id"], ["repo_paths.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_path_id"], ["repo_paths.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dependencies_repo_id"), "dependencies", ["repo_id"], unique=False)

    # ---- findings: BIGINT identity PK + nullable path_id FK ----
    op.create_table(
        "findings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column(
            "severity",
            # create_type=False: the finding_severity Postgres ENUM TYPE is a
            # separate object from the findings table and was never dropped
            # (dropping a table doesn't drop enum types it referenced) -- it
            # still exists from the original migration, so re-declaring this
            # column without create_type=False would try to CREATE TYPE
            # finding_severity again and fail with DuplicateObject.
            postgresql.ENUM("low", "med", "high", name="finding_severity", create_type=False),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("path_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_sha", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["path_id"], ["repo_paths.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_findings_repo_id"), "findings", ["repo_id"], unique=False)

    # ---- file_metrics: BIGINT identity PK, file_id becomes BIGINT ----
    op.create_table(
        "file_metrics",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("risk_confidence", sa.Float(), nullable=True),
        sa.Column("hotspot_rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )


def downgrade() -> None:
    op.drop_table("file_metrics")

    op.drop_index(op.f("ix_findings_repo_id"), table_name="findings")
    op.drop_table("findings")

    op.drop_index(op.f("ix_dependencies_repo_id"), table_name="dependencies")
    op.drop_table("dependencies")

    op.drop_index("ix_coupling_repo_id_degree", table_name="coupling")
    op.drop_index(op.f("ix_coupling_repo_id"), table_name="coupling")
    op.drop_table("coupling")

    op.drop_index("ix_files_repo_id_path_id", table_name="files")
    op.drop_index("ix_files_repo_id_path", table_name="files")
    op.drop_index(op.f("ix_files_repo_id"), table_name="files")
    op.drop_table("files")

    op.drop_index(op.f("ix_commits_sha"), table_name="commits")
    op.drop_index("ix_commits_repo_id_sha", table_name="commits")
    op.drop_index(op.f("ix_commits_repo_id"), table_name="commits")
    op.drop_table("commits")

    op.drop_index(op.f("ix_repo_paths_repo_id"), table_name="repo_paths")
    op.drop_table("repo_paths")

    # ---- Recreate the pre-Phase-1 (UUID PK, commit_files-based) shape ----
    op.create_table(
        "commits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("sha", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=False),
        sa.Column("author_email", sa.String(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_fix", sa.Boolean(), nullable=False),
        sa.Column("is_revert", sa.Boolean(), nullable=False),
        sa.Column("files_changed", sa.Integer(), nullable=False),
        sa.Column("insertions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commits_repo_id"), "commits", ["repo_id"], unique=False)
    op.create_index("ix_commits_repo_id_sha", "commits", ["repo_id", "sha"], unique=False)
    op.create_index(op.f("ix_commits_sha"), "commits", ["sha"], unique=False)

    op.create_table(
        "coupling",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("file_a_path", sa.String(), nullable=False),
        sa.Column("file_b_path", sa.String(), nullable=False),
        sa.Column("shared_revs", sa.Integer(), nullable=False),
        sa.Column("coupling_degree", sa.Float(), nullable=False),
        sa.Column("avg_revs", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_coupling_repo_id"), "coupling", ["repo_id"], unique=False)
    op.create_index(
        "ix_coupling_repo_id_degree", "coupling", ["repo_id", "coupling_degree"], unique=False
    )

    op.create_table(
        "dependencies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("from_path", sa.String(), nullable=False),
        sa.Column("to_path", sa.String(), nullable=False),
        sa.Column("dep_type", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dependencies_repo_id"), "dependencies", ["repo_id"], unique=False)

    op.create_table(
        "files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("current_loc", sa.Integer(), nullable=False),
        sa.Column("complexity", sa.Float(), nullable=False),
        sa.Column("churn_total", sa.Integer(), nullable=False),
        sa.Column("commit_count", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_files_repo_id"), "files", ["repo_id"], unique=False)
    op.create_index("ix_files_repo_id_path", "files", ["repo_id", "path"], unique=False)

    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column(
            "severity",  # create_type=False -- see the matching comment in upgrade() above
            postgresql.ENUM("low", "med", "high", name="finding_severity", create_type=False),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("evidence_sha", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_findings_repo_id"), "findings", ["repo_id"], unique=False)

    op.create_table(
        "commit_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("commit_id", sa.UUID(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["commit_id"], ["commits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commit_files_commit_id", "commit_files", ["commit_id"], unique=False)

    op.create_table(
        "file_metrics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("risk_confidence", sa.Float(), nullable=True),
        sa.Column("hotspot_rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
