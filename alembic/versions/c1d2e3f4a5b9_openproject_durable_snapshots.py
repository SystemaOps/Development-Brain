"""openproject durable snapshots

Revision ID: c1d2e3f4a5b9
Revises: b1c2d3e4f5a8
Create Date: 2026-09-19 10:10:00.000000

Adds the durable normalized OpenProject work-item snapshot store so webhook
and pull diffs survive restarts.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b9'
down_revision: Union[str, None] = 'b1c2d3e4f5a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'openproject_work_item_snapshots',
        sa.Column('external_id', sa.String(length=500), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=True),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('external_id'),
    )


def downgrade() -> None:
    op.drop_table('openproject_work_item_snapshots')