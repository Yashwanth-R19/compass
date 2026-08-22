"""add users, share_links, private repo access

Revision ID: 2c20265ab4ca
Revises: c738e176e086
Create Date: 2026-08-22 22:00:55.092890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c20265ab4ca'
down_revision: Union[str, None] = 'c738e176e086'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('github_id', sa.BigInteger(), nullable=False),
    sa.Column('github_login', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('avatar_url', sa.Text(), nullable=True),
    sa.Column('access_token_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('token_scopes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_github_id'), 'users', ['github_id'], unique=True)
    op.create_table('share_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.Text(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='share_links_created_by_fkey', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['analysis_runs.id'], name='share_links_run_id_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_share_links_run_id'), 'share_links', ['run_id'], unique=False)
    op.create_index(op.f('ix_share_links_slug'), 'share_links', ['slug'], unique=True)
    op.add_column('analysis_runs', sa.Column('triggered_by_user_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'analysis_runs_triggered_by_user_id_fkey',
        'analysis_runs', 'users', ['triggered_by_user_id'], ['id'], ondelete='SET NULL',
    )
    op.add_column('repos', sa.Column('owner_user_id', sa.UUID(), nullable=True))
    # server_default=false() is required here, not just the ORM-level Python
    # default -- `repos` is a populated table in every deployed environment,
    # and Postgres rejects adding a NOT NULL column with no default against
    # existing rows (plan/RULES.md sec 7). Dropped again below once every
    # existing row has a concrete value, matching the ORM's Python-side
    # `default=False` (new rows never need the server default after this).
    op.add_column('repos', sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('repos', 'is_private', server_default=None)
    op.add_column('repos', sa.Column('visibility_checked_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_repos_owner_user_id'), 'repos', ['owner_user_id'], unique=False)
    op.create_foreign_key(
        'repos_owner_user_id_fkey',
        'repos', 'users', ['owner_user_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('repos_owner_user_id_fkey', 'repos', type_='foreignkey')
    op.drop_index(op.f('ix_repos_owner_user_id'), table_name='repos')
    op.drop_column('repos', 'visibility_checked_at')
    op.drop_column('repos', 'is_private')
    op.drop_column('repos', 'owner_user_id')
    op.drop_constraint('analysis_runs_triggered_by_user_id_fkey', 'analysis_runs', type_='foreignkey')
    op.drop_column('analysis_runs', 'triggered_by_user_id')
    op.drop_index(op.f('ix_share_links_slug'), table_name='share_links')
    op.drop_index(op.f('ix_share_links_run_id'), table_name='share_links')
    op.drop_table('share_links')
    op.drop_index(op.f('ix_users_github_id'), table_name='users')
    op.drop_table('users')
