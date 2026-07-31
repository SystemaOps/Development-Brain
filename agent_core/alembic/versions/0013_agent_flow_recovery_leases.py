"""add agent flow recovery leases

Revision ID: 0013_agent_flow_recovery_leases
Revises: 0012_agent_platform_flows
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_agent_flow_recovery_leases"
down_revision = "0012_agent_platform_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_platform_flows",
        sa.Column(
            "recovery_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "agent_platform_flows",
        sa.Column(
            "lease_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_platform_flows",
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "agent_platform_flows",
        sa.Column(
            "lease_acquired_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_platform_flows",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE agent_platform_flows
        SET lease_id = gen_random_uuid(),
            lease_owner = 'migration-recovery',
            lease_acquired_at = updated_at,
            lease_expires_at = updated_at
        WHERE status = 'running'
          AND lease_id IS NULL
        """
    )
    op.create_index(
        "idx_agent_platform_flows_recoverable",
        "agent_platform_flows",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agent_platform_flows_recoverable",
        table_name="agent_platform_flows",
    )
    op.drop_column("agent_platform_flows", "lease_expires_at")
    op.drop_column("agent_platform_flows", "lease_acquired_at")
    op.drop_column("agent_platform_flows", "lease_owner")
    op.drop_column("agent_platform_flows", "lease_id")
    op.drop_column("agent_platform_flows", "recovery_count")
