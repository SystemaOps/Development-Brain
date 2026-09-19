"""comments and attachments

Revision ID: b1c2d3e4f5a8
Revises: a1b2c3d4e5f7
Create Date: 2026-09-19 10:05:00.000000

Adds canonical ``comments`` and ``attachments`` tables for work-management
provider activities and attachments.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a8'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'comments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('work_item_id', sa.UUID(), nullable=False),
        sa.Column('author_id', sa.UUID(), nullable=True),
        sa.Column('author_name', sa.String(length=255), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_refs', postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comments_work_item', 'comments', ['work_item_id'], unique=False)
    op.create_table(
        'attachments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('work_item_id', sa.UUID(), nullable=False),
        sa.Column('file_name', sa.String(length=500), nullable=False),
        sa.Column('content_type', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('download_url', sa.Text(), nullable=True),
        sa.Column('content_ingested', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_refs', postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_attachments_work_item', 'attachments', ['work_item_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_attachments_work_item', table_name='attachments')
    op.drop_table('attachments')
    op.drop_index('ix_comments_work_item', table_name='comments')
    op.drop_table('comments')