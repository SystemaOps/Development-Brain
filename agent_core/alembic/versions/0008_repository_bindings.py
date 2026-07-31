"""add repository bindings

Revision ID: 0008_repository_bindings
Revises: 0007_approval_records
Create Date: 2026-07-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_repository_bindings"
down_revision = "0007_approval_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_bindings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository_key", sa.String(length=80), nullable=False),
        sa.Column("mount_path", sa.Text(), nullable=False),
        sa.Column("access_mode", sa.String(length=40), nullable=False, server_default="READ_ONLY"),
        sa.Column(
            "write_allowlist",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "denylist",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "command_allowlist",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "binding_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "access_mode IN ('READ_ONLY', 'READ_WRITE')",
            name="ck_repository_bindings_access_mode",
        ),
        sa.UniqueConstraint(
            "project_id",
            "repository_key",
            name="uq_repository_bindings_project_key",
        ),
    )
    op.create_index(
        "idx_repository_bindings_project",
        "repository_bindings",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_repository_bindings_project", table_name="repository_bindings")
    op.drop_table("repository_bindings")
