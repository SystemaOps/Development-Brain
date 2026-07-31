"""add webhook event idempotency key

Revision ID: 0002_webhook_event_idempotency
Revises: 0001_current_baseline
Create Date: 2026-07-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_webhook_event_idempotency"
down_revision = "0001_current_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pm_webhook_events",
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
    )
    op.execute(
        """
        UPDATE pm_webhook_events
        SET idempotency_key = 'legacy:' || id::text
        WHERE idempotency_key IS NULL
        """
    )
    op.alter_column("pm_webhook_events", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_pm_webhook_events_idempotency_key",
        "pm_webhook_events",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_pm_webhook_events_idempotency_key",
        "pm_webhook_events",
        type_="unique",
    )
    op.drop_column("pm_webhook_events", "idempotency_key")
