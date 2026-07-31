"""add coding attempts

Revision ID: 0010_coding_attempts
Revises: 0009_repository_index
Create Date: 2026-07-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_coding_attempts"
down_revision = "0009_repository_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coding_attempts",
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
        sa.Column("task_key", sa.String(length=160), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("base_commit_sha", sa.String(length=80), nullable=True),
        sa.Column("branch", sa.String(length=200), nullable=True),
        sa.Column(
            "changed_files",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "command_results",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "rollback_plan",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("final_diff", sa.Text(), nullable=True),
        sa.Column(
            "error_summary",
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
            "status IN ('created', 'running', 'succeeded', 'failed', 'blocked', 'rolled_back')",
            name="ck_coding_attempts_status",
        ),
        sa.UniqueConstraint(
            "project_id",
            "repository_key",
            "task_key",
            "attempt_number",
            name="uq_coding_attempts_project_task_attempt",
        ),
    )
    op.create_index(
        "idx_coding_attempts_project_task",
        "coding_attempts",
        ["project_id", "task_key", "attempt_number"],
    )
    op.create_index(
        "idx_coding_attempts_project_status",
        "coding_attempts",
        ["project_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_coding_attempts_project_status", table_name="coding_attempts")
    op.drop_index("idx_coding_attempts_project_task", table_name="coding_attempts")
    op.drop_table("coding_attempts")
