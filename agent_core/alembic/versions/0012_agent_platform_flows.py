"""add durable agent platform flows

Revision ID: 0012_agent_platform_flows
Revises: 0011_agent_platform_persistence
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_agent_platform_flows"
down_revision = "0011_agent_platform_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_platform_flows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workflow_id", sa.String(length=120), nullable=False),
        sa.Column("project_key", sa.String(length=80), nullable=False),
        sa.Column("task_key", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "step_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("current_agent_type", sa.String(length=80), nullable=True),
        sa.Column(
            "current_execution_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("pending_action", sa.String(length=80), nullable=True),
        sa.Column("pending_agent_type", sa.String(length=80), nullable=True),
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column(
            "resume_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "last_approval_decision",
            sa.String(length=40),
            nullable=True,
        ),
        sa.Column(
            "flow_json",
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
            "status IN ("
            "'running', 'completed', 'waiting_for_approval', "
            "'waiting_for_clarification', 'transition_pending', 'escalated', "
            "'max_steps_exceeded', 'changes_requested', 'cancelled'"
            ")",
            name="ck_agent_platform_flows_status",
        ),
        sa.UniqueConstraint(
            "project_key",
            "workflow_id",
            name="uq_agent_platform_flows_project_workflow",
        ),
    )
    op.create_index(
        "idx_agent_platform_flows_project_status",
        "agent_platform_flows",
        ["project_key", "status", "updated_at"],
    )
    op.create_index(
        "idx_agent_platform_flows_current_execution",
        "agent_platform_flows",
        ["current_execution_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agent_platform_flows_current_execution",
        table_name="agent_platform_flows",
    )
    op.drop_index(
        "idx_agent_platform_flows_project_status",
        table_name="agent_platform_flows",
    )
    op.drop_table("agent_platform_flows")
