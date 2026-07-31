"""add queued agent flow status

Revision ID: 0014_queued_agent_flows
Revises: 0013_agent_flow_recovery_leases
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op

revision = "0014_queued_agent_flows"
down_revision = "0013_agent_flow_recovery_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_agent_platform_flows_status",
        "agent_platform_flows",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_platform_flows_status",
        "agent_platform_flows",
        "status IN ("
        "'queued', 'running', 'completed', 'waiting_for_approval', "
        "'waiting_for_clarification', 'transition_pending', 'escalated', "
        "'max_steps_exceeded', 'changes_requested', 'cancelled'"
        ")",
    )
    op.create_index(
        "idx_agent_platform_flows_claimable",
        "agent_platform_flows",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agent_platform_flows_claimable",
        table_name="agent_platform_flows",
    )
    op.execute(
        """
        UPDATE agent_platform_flows
        SET status = 'escalated',
            flow_json = jsonb_set(
                jsonb_set(flow_json, '{status}', '"escalated"'::jsonb),
                '{reason}',
                '"Queued flow escalated during migration downgrade."'::jsonb
            )
        WHERE status = 'queued'
        """
    )
    op.drop_constraint(
        "ck_agent_platform_flows_status",
        "agent_platform_flows",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_platform_flows_status",
        "agent_platform_flows",
        "status IN ("
        "'running', 'completed', 'waiting_for_approval', "
        "'waiting_for_clarification', 'transition_pending', 'escalated', "
        "'max_steps_exceeded', 'changes_requested', 'cancelled'"
        ")",
    )
