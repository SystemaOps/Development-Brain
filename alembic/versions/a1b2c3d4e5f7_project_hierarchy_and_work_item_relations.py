"""project hierarchy and work item relations

Revision ID: a1b2c3d4e5f7
Revises: f3a1c2d4e5f6
Create Date: 2026-09-19 10:00:00.000000

Adds ``projects.parent_id`` (project hierarchy) and the canonical
``work_item_relations`` table.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'f3a1c2d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column('parent_id', sa.UUID(), nullable=True),
    )
    op.create_index('ix_projects_parent_id', 'projects', ['parent_id'], unique=False)
    op.create_table(
        'work_item_relations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('source_work_item_id', sa.UUID(), nullable=False),
        sa.Column('target_work_item_id', sa.UUID(), nullable=False),
        sa.Column('relation_type', sa.String(length=50), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_refs', postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'source_work_item_id', 'target_work_item_id', 'relation_type',
            name='uq_work_item_relation',
        ),
    )
    op.create_index(
        'ix_work_item_relations_source', 'work_item_relations', ['source_work_item_id'],
        unique=False,
    )
    op.create_index(
        'ix_work_item_relations_target', 'work_item_relations', ['target_work_item_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_work_item_relations_target', table_name='work_item_relations')
    op.drop_index('ix_work_item_relations_source', table_name='work_item_relations')
    op.drop_table('work_item_relations')
    op.drop_index('ix_projects_parent_id', table_name='projects')
    op.drop_column('projects', 'parent_id')