"""add agent execution tracking

Revision ID: 0004_agent_executions
Revises: 0003_agent_job_leases
Create Date: 2026-07-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_agent_executions"
down_revision = "0003_agent_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_executions",
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
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column(
            "trigger_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pm_webhook_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column(
            "config_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('created', 'running', 'waiting', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_executions_status",
        ),
    )
    op.create_index(
        "idx_agent_executions_thread_started",
        "agent_executions",
        ["thread_id", "started_at"],
    )
    op.create_index(
        "idx_agent_executions_project_status",
        "agent_executions",
        ["project_id", "status"],
    )
    op.create_index(
        "idx_agent_executions_trigger_event",
        "agent_executions",
        ["trigger_event_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_executions_trigger_event", table_name="agent_executions")
    op.drop_index("idx_agent_executions_project_status", table_name="agent_executions")
    op.drop_index("idx_agent_executions_thread_started", table_name="agent_executions")
    op.drop_table("agent_executions")
