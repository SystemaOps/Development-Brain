"""add OpenProject reconciliation snapshots

Revision ID: 0006_op_reconciliation
Revises: 0005_op_outbound_ops
Create Date: 2026-07-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_op_reconciliation"
down_revision = "0005_op_outbound_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openproject_reconciliation_snapshots",
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
        sa.Column("outbound_idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column("target_artifact_type", sa.String(length=80), nullable=False),
        sa.Column("target_external_id", sa.Text(), nullable=False),
        sa.Column(
            "before_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("before_activities_payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "agent_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "detected_human_edits",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_openproject_reconciliation_snapshots_target",
        "openproject_reconciliation_snapshots",
        ["target_artifact_type", "target_external_id", "captured_at"],
    )
    op.create_index(
        "idx_openproject_reconciliation_snapshots_outbound_key",
        "openproject_reconciliation_snapshots",
        ["outbound_idempotency_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_openproject_reconciliation_snapshots_outbound_key",
        table_name="openproject_reconciliation_snapshots",
    )
    op.drop_index(
        "idx_openproject_reconciliation_snapshots_target",
        table_name="openproject_reconciliation_snapshots",
    )
    op.drop_table("openproject_reconciliation_snapshots")
