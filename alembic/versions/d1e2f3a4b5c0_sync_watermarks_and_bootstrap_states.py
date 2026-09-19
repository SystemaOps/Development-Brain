"""sync watermarks and bootstrap states

Revision ID: d1e2f3a4b5c0
Revises: c1d2e3f4a5b9
Create Date: 2026-09-19 10:15:00.000000

Adds durable provider pull-sync watermarks and provider bootstrap progress.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c0'
down_revision: Union[str, None] = 'c1d2e3f4a5b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'provider_sync_watermarks',
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('sync_key', sa.String(length=500), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_external_id', sa.String(length=500), nullable=True),
        sa.Column('bootstrap_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('provider', 'sync_key'),
    )
    op.create_table(
        'provider_bootstrap_states',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('stage', sa.String(length=50), nullable=False),
        sa.Column('last_page', sa.BigInteger(), nullable=False),
        sa.Column('items_processed', sa.BigInteger(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'provider', name='uq_provider_bootstrap_state'),
    )


def downgrade() -> None:
    op.drop_table('provider_bootstrap_states')
    op.drop_table('provider_sync_watermarks')