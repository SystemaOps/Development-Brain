"""Provider sync watermark domain model.

Durable per-provider cursors used by pull reconciliation.  A watermark records
how far the brain has synchronized a provider stream (e.g. OpenProject work
items of one project) so periodic pulls can resume without re-processing
history.  The watermark is advanced only after a batch has been processed;
idempotent event handling makes the at-least-once delivery safe.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ProviderSyncWatermark(BaseModel):
    provider: str
    sync_key: str
    last_synced_at: datetime | None = None
    last_external_id: str | None = None
    bootstrap_completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = ["ProviderSyncWatermark"]
