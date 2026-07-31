"""add agent job leases and retry scheduling

Revision ID: 0003_agent_job_leases
Revises: 0002_webhook_event_idempotency
Create Date: 2026-07-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_agent_job_leases"
down_revision = "0002_webhook_event_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pm_webhook_events",
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "agent_jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_jobs",
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("agent_jobs", sa.Column("lease_owner", sa.Text(), nullable=True))
    op.add_column(
        "agent_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("agent_jobs", sa.Column("last_error", postgresql.JSONB(), nullable=True))

    op.execute(
        "ALTER TABLE pm_webhook_events "
        "DROP CONSTRAINT IF EXISTS pm_webhook_events_processing_status_check"
    )
    op.execute(
        "ALTER TABLE pm_webhook_events "
        "DROP CONSTRAINT IF EXISTS ck_pm_webhook_events_processing_status"
    )
    op.create_check_constraint(
        "ck_pm_webhook_events_processing_status",
        "pm_webhook_events",
        "processing_status IN ('pending', 'processing', 'processed', 'failed', 'dead_letter')",
    )

    op.execute("ALTER TABLE agent_jobs DROP CONSTRAINT IF EXISTS agent_jobs_status_check")
    op.execute("ALTER TABLE agent_jobs DROP CONSTRAINT IF EXISTS ck_agent_jobs_status")
    op.create_check_constraint(
        "ck_agent_jobs_status",
        "agent_jobs",
        "status IN ('queued', 'running', 'done', 'failed', 'dead_letter')",
    )

    op.create_index(
        "idx_pm_webhook_events_retry",
        "pm_webhook_events",
        ["processing_status", "retry_at"],
    )
    op.create_index("idx_agent_jobs_retry", "agent_jobs", ["status", "retry_at"])
    op.create_index("idx_agent_jobs_lease", "agent_jobs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("idx_agent_jobs_lease", table_name="agent_jobs")
    op.drop_index("idx_agent_jobs_retry", table_name="agent_jobs")
    op.drop_index("idx_pm_webhook_events_retry", table_name="pm_webhook_events")

    op.execute("ALTER TABLE agent_jobs DROP CONSTRAINT IF EXISTS ck_agent_jobs_status")
    op.create_check_constraint(
        "ck_agent_jobs_status",
        "agent_jobs",
        "status IN ('queued', 'running', 'done', 'failed')",
    )

    op.execute(
        "ALTER TABLE pm_webhook_events "
        "DROP CONSTRAINT IF EXISTS ck_pm_webhook_events_processing_status"
    )
    op.create_check_constraint(
        "ck_pm_webhook_events_processing_status",
        "pm_webhook_events",
        "processing_status IN ('pending', 'processing', 'processed', 'failed')",
    )

    op.drop_column("agent_jobs", "last_error")
    op.drop_column("agent_jobs", "lease_expires_at")
    op.drop_column("agent_jobs", "lease_owner")
    op.drop_column("agent_jobs", "retry_at")
    op.drop_column("agent_jobs", "attempt_count")
    op.drop_column("pm_webhook_events", "retry_at")
