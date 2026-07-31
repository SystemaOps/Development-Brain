"""add OpenProject outbound operation idempotency

Revision ID: 0005_op_outbound_ops
Revises: 0004_agent_executions
Create Date: 2026-07-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_op_outbound_ops"
down_revision = "0004_agent_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openproject_outbound_operations",
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
            nullable=True,
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("target_artifact_type", sa.String(length=80), nullable=True),
        sa.Column("target_external_id", sa.Text(), nullable=True),
        sa.Column(
            "request_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_openproject_outbound_operations_idempotency_key",
        ),
        sa.CheckConstraint(
            "operation_type IN ('create_or_update_work_package', 'add_comment')",
            name="ck_openproject_outbound_operations_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_openproject_outbound_operations_status",
        ),
    )
    op.create_index(
        "idx_openproject_outbound_operations_status",
        "openproject_outbound_operations",
        ["status", "created_at"],
    )
    op.create_index(
        "idx_openproject_outbound_operations_target",
        "openproject_outbound_operations",
        ["target_artifact_type", "target_external_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_openproject_outbound_operations_target",
        table_name="openproject_outbound_operations",
    )
    op.drop_index(
        "idx_openproject_outbound_operations_status",
        table_name="openproject_outbound_operations",
    )
    op.drop_table("openproject_outbound_operations")

