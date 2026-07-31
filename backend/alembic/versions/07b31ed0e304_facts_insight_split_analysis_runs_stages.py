"""facts/insight split: analysis_runs + analysis_stages

Revision ID: 07b31ed0e304
Revises: ac5b5434d0e6
Create Date: 2026-07-31 13:05:51.855086

Phase 2 (COMPASS_PLAN.md sec 4 / plan/PHASE_02_staged_pipeline.md): splits
the data model into a Facts layer (repo_paths/commits/files/dependencies,
keyed by repo_id, replaced only when a repo's head_sha changes) and an
Insight layer (coupling/file_metrics/findings/health, keyed by the new
``analysis_runs.id``, versioned rather than overwritten). This is what makes
progressive reveal, A/B compare (Phase 17), and LRU eviction (Phase 21)
possible without a later rewrite of every engine.

  * New ``analysis_runs`` (one row per analysis attempt) and
    ``analysis_stages`` (one row per (run, stage-name), pre-created pending)
    tables.
  * ``repos`` gains ``head_sha`` (the commit the persisted Facts were mined
    from) and ``current_run_id`` (the live analysis_runs row).
  * ``coupling``, ``findings``, ``health`` gain ``analysis_run_id``.
  * ``file_metrics`` is re-keyed from ``file_id`` (FK to the Facts-layer
    ``files.id``, which gets wiped-and-reinserted with fresh ids whenever
    Facts are replaced) to ``path_id`` (FK to the now-permanent
    ``repo_paths.id``) plus a new ``repo_id`` column -- otherwise a repo
    getting new commits would cascade-delete every OLDER run's file_metrics
    the moment its Facts were replaced, breaking "old runs stay diffable"
    before it ever shipped. See app/db/models.py's RepoPath/FileMetrics
    docstrings for the full reasoning. ``repo_paths`` itself is unchanged by
    this migration (no new column) but becomes append-only from this point
    on -- app/db/wipe.py's wipe_facts() (replacing wipe_repo_data) no longer
    deletes it.
  * ``health.repo_id`` loses its ``unique=True`` (one row per repo_id) in
    favor of ``unique=True`` on ``analysis_run_id`` (one row per run) --
    existing ``health`` rows are cleared first (see data note below), same
    "no production data exists yet, re-ingest after migrating" precedent as
    ac5b5434d0e6.

Data note: this repo's dev DB already has a few orphaned ``health`` rows
left over from repos whose Facts (commits/files/coupling/etc.) are already
empty -- i.e. stale rows with nothing behind them. ``analysis_run_id`` is
NOT NULL and there is no real run to backfill them against, so they are
deleted outright before the column is added. ``coupling``/``file_metrics``/
``findings`` have zero rows in this environment, so no equivalent backfill
is needed there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "07b31ed0e304"
down_revision: str | None = "ac5b5434d0e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("running", "ready", "failed", "superseded", name="analysis_run_status"),
            nullable=False,
        ),
        sa.Column("head_sha", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("engine_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_runs_repo_id"), "analysis_runs", ["repo_id"], unique=False)
    op.create_index(
        "ix_analysis_runs_repo_id_started_at",
        "analysis_runs",
        ["repo_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "analysis_stages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", "skipped", name="stage_status"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "name", name="uq_analysis_stages_run_id_name"),
    )
    op.create_index(
        op.f("ix_analysis_stages_run_id"), "analysis_stages", ["run_id"], unique=False
    )

    op.add_column("coupling", sa.Column("analysis_run_id", sa.UUID(), nullable=False))
    op.create_index("ix_coupling_run_id", "coupling", ["analysis_run_id"], unique=False)
    op.create_foreign_key(
        "coupling_analysis_run_id_fkey",
        "coupling",
        "analysis_runs",
        ["analysis_run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.add_column("findings", sa.Column("analysis_run_id", sa.UUID(), nullable=False))
    op.create_index(
        op.f("ix_findings_analysis_run_id"), "findings", ["analysis_run_id"], unique=False
    )
    op.create_foreign_key(
        "findings_analysis_run_id_fkey",
        "findings",
        "analysis_runs",
        ["analysis_run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # file_metrics: re-key from file_id (Facts) to path_id (permanent) --
    # see module docstring. Table is empty in every known environment, so no
    # backfill is attempted; a fresh analysis run repopulates it.
    op.drop_constraint("file_metrics_file_id_key", "file_metrics", type_="unique")
    op.drop_constraint("file_metrics_file_id_fkey", "file_metrics", type_="foreignkey")
    op.drop_column("file_metrics", "file_id")
    op.add_column("file_metrics", sa.Column("analysis_run_id", sa.UUID(), nullable=False))
    op.add_column("file_metrics", sa.Column("repo_id", sa.UUID(), nullable=False))
    op.add_column("file_metrics", sa.Column("path_id", sa.BigInteger(), nullable=False))
    op.create_index(
        op.f("ix_file_metrics_analysis_run_id"), "file_metrics", ["analysis_run_id"], unique=False
    )
    op.create_index(op.f("ix_file_metrics_repo_id"), "file_metrics", ["repo_id"], unique=False)
    op.create_unique_constraint(
        "uq_file_metrics_run_id_path_id", "file_metrics", ["analysis_run_id", "path_id"]
    )
    op.create_foreign_key(
        "file_metrics_repo_id_fkey", "file_metrics", "repos", ["repo_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "file_metrics_analysis_run_id_fkey",
        "file_metrics",
        "analysis_runs",
        ["analysis_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "file_metrics_path_id_fkey",
        "file_metrics",
        "repo_paths",
        ["path_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # health: re-keyed from "one row per repo_id" to "one row per
    # analysis_run_id". Existing rows are orphaned dev-DB leftovers with no
    # Facts behind them (see module docstring) -- cleared rather than
    # backfilled, same precedent as ac5b5434d0e6.
    op.execute("DELETE FROM health")
    op.add_column("health", sa.Column("analysis_run_id", sa.UUID(), nullable=False))
    op.drop_index("ix_health_repo_id", table_name="health")
    op.create_index(op.f("ix_health_repo_id"), "health", ["repo_id"], unique=False)
    op.create_index(
        op.f("ix_health_analysis_run_id"), "health", ["analysis_run_id"], unique=True
    )
    op.create_foreign_key(
        "health_analysis_run_id_fkey",
        "health",
        "analysis_runs",
        ["analysis_run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.add_column("repos", sa.Column("head_sha", sa.Text(), nullable=True))
    op.add_column("repos", sa.Column("current_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "repos_current_run_id_fkey",
        "repos",
        "analysis_runs",
        ["current_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("repos_current_run_id_fkey", "repos", type_="foreignkey")
    op.drop_column("repos", "current_run_id")
    op.drop_column("repos", "head_sha")

    op.drop_constraint("health_analysis_run_id_fkey", "health", type_="foreignkey")
    op.drop_index(op.f("ix_health_analysis_run_id"), table_name="health")
    op.drop_index(op.f("ix_health_repo_id"), table_name="health")
    op.create_index("ix_health_repo_id", "health", ["repo_id"], unique=True)
    op.drop_column("health", "analysis_run_id")

    op.drop_constraint("findings_analysis_run_id_fkey", "findings", type_="foreignkey")
    op.drop_index(op.f("ix_findings_analysis_run_id"), table_name="findings")
    op.drop_column("findings", "analysis_run_id")

    op.drop_constraint("file_metrics_repo_id_fkey", "file_metrics", type_="foreignkey")
    op.drop_constraint("file_metrics_analysis_run_id_fkey", "file_metrics", type_="foreignkey")
    op.drop_constraint("file_metrics_path_id_fkey", "file_metrics", type_="foreignkey")
    op.drop_constraint("uq_file_metrics_run_id_path_id", "file_metrics", type_="unique")
    op.drop_index(op.f("ix_file_metrics_repo_id"), table_name="file_metrics")
    op.drop_index(op.f("ix_file_metrics_analysis_run_id"), table_name="file_metrics")
    op.drop_column("file_metrics", "path_id")
    op.drop_column("file_metrics", "repo_id")
    op.drop_column("file_metrics", "analysis_run_id")
    op.add_column(
        "file_metrics", sa.Column("file_id", sa.BIGINT(), autoincrement=False, nullable=False)
    )
    op.create_unique_constraint("file_metrics_file_id_key", "file_metrics", ["file_id"])
    op.create_foreign_key(
        "file_metrics_file_id_fkey", "file_metrics", "files", ["file_id"], ["id"], ondelete="CASCADE"
    )

    op.drop_constraint("coupling_analysis_run_id_fkey", "coupling", type_="foreignkey")
    op.drop_index("ix_coupling_run_id", table_name="coupling")
    op.drop_column("coupling", "analysis_run_id")

    op.drop_index(op.f("ix_analysis_stages_run_id"), table_name="analysis_stages")
    op.drop_table("analysis_stages")
    op.drop_index("ix_analysis_runs_repo_id_started_at", table_name="analysis_runs")
    op.drop_index(op.f("ix_analysis_runs_repo_id"), table_name="analysis_runs")
    op.drop_table("analysis_runs")

    sa.Enum(name="stage_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="analysis_run_status").drop(op.get_bind(), checkfirst=True)
