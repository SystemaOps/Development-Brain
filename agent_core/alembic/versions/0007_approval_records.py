"""add approval records

Revision ID: 0007_approval_records
Revises: 0006_op_reconciliation
Create Date: 2026-07-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_approval_records"
down_revision = "0006_op_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_records",
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
        sa.Column(
            "planning_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("planning_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "plan_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plan_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "external_artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_system", sa.String(length=60), nullable=False, server_default="openproject"),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("external_project_id", sa.Text(), nullable=True),
        sa.Column("external_work_package_id", sa.Text(), nullable=True),
        sa.Column("external_comment_id", sa.Text(), nullable=True),
        sa.Column("approval_scope", sa.String(length=40), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "approval_scope IN ('planning', 'task_completion')",
            name="ck_approval_records_scope",
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'changes_requested', 'cancelled')",
            name="ck_approval_records_decision",
        ),
        sa.UniqueConstraint(
            "source_system",
            "source_event_id",
            "approval_scope",
            "decision",
            name="uq_approval_records_source_decision",
        ),
    )
    op.create_index(
        "idx_approval_records_project_scope",
        "approval_records",
        ["project_id", "approval_scope", "created_at"],
    )
    op.create_index(
        "idx_approval_records_source_event",
        "approval_records",
        ["source_system", "source_event_id"],
    )
    op.create_index(
        "idx_approval_records_external_work_package",
        "approval_records",
        ["source_system", "external_work_package_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_approval_records_external_work_package",
        table_name="approval_records",
    )
    op.drop_index("idx_approval_records_source_event", table_name="approval_records")
    op.drop_index("idx_approval_records_project_scope", table_name="approval_records")
    op.drop_table("approval_records")
