"""add agent platform persistence

Revision ID: 0011_agent_platform_persistence
Revises: 0010_coding_attempts
Create Date: 2026-07-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_agent_platform_persistence"
down_revision = "0010_coding_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_platform_checkpoints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_key", sa.String(length=80), nullable=False),
        sa.Column("workflow_id", sa.String(length=120), nullable=False),
        sa.Column("agent_type", sa.String(length=80), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=160), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=120), nullable=False),
        sa.Column("checkpoint_key", sa.Text(), nullable=False),
        sa.Column(
            "state_json",
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
        sa.UniqueConstraint(
            "project_key",
            "workflow_id",
            "agent_type",
            "agent_instance_id",
            "execution_id",
            "thread_id",
            "checkpoint_id",
            name="uq_agent_platform_checkpoints_identity",
        ),
    )
    op.create_index(
        "idx_agent_platform_checkpoints_namespace",
        "agent_platform_checkpoints",
        ["project_key", "workflow_id", "agent_type", "agent_instance_id", "created_at"],
    )
    op.create_index(
        "idx_agent_platform_checkpoints_execution",
        "agent_platform_checkpoints",
        ["execution_id", "agent_type", "created_at"],
    )

    op.create_table(
        "agent_platform_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_key", sa.String(length=80), nullable=False),
        sa.Column("task_key", sa.String(length=160), nullable=True),
        sa.Column("agent_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("next_action", sa.String(length=80), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("result_type", sa.String(length=120), nullable=False),
        sa.Column(
            "result_json",
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
    )
    op.create_index(
        "idx_agent_platform_results_execution",
        "agent_platform_results",
        ["execution_id", "agent_type", "created_at"],
    )
    op.create_index(
        "idx_agent_platform_results_project_status",
        "agent_platform_results",
        ["project_key", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_platform_results_project_status", table_name="agent_platform_results")
    op.drop_index("idx_agent_platform_results_execution", table_name="agent_platform_results")
    op.drop_table("agent_platform_results")
    op.drop_index("idx_agent_platform_checkpoints_execution", table_name="agent_platform_checkpoints")
    op.drop_index("idx_agent_platform_checkpoints_namespace", table_name="agent_platform_checkpoints")
    op.drop_table("agent_platform_checkpoints")
