"""drop snapshots

Revision ID: a3f1c9d2e8b4
Revises: 70017ee3b25d
Create Date: 2026-11-18 00:00:00.000000

The evolution timeline (TimelineEngine + the /timeline endpoint + the
Evolution page) was removed, so the ``snapshots`` table it populated is
dropped. ``downgrade()`` recreates it exactly as the initial schema did.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3f1c9d2e8b4'
down_revision: Union[str, None] = '70017ee3b25d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_snapshots_repo_id', table_name='snapshots')
    op.drop_index(op.f('ix_snapshots_analysis_run_id'), table_name='snapshots')
    op.drop_table('snapshots')


def downgrade() -> None:
    op.create_table('snapshots',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('analysis_run_id', sa.UUID(), nullable=False),
    sa.Column('repo_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('commit_sha', sa.Text(), nullable=False),
    sa.Column('at_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('commit_index', sa.Integer(), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['analysis_run_id'], ['analysis_runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('analysis_run_id', 'position', name='uq_snapshots_run_id_position')
    )
    op.create_index(op.f('ix_snapshots_analysis_run_id'), 'snapshots', ['analysis_run_id'], unique=False)
    op.create_index('ix_snapshots_repo_id', 'snapshots', ['repo_id'], unique=False)
