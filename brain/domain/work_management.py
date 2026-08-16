"""Work-management integration domain model (Phase 14).

Defines the canonical <-> provider field mapping (Task 14.1), the durable
integration mapping row (Task 14.4), and the sync-conflict record (Task 14.5).

External work-management systems (OpenProject, Jira) are providers behind the
``WorkManagementPort``; the brain's canonical ``WorkItem`` never changes shape
when the provider is swapped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import WorkItemId


class SyncState(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    CONFLICT = "conflict"
    ERROR = "error"


class FieldMapping(BaseModel):
    """One canonical field mapped to a provider field (Task 14.1)."""

    canonical_field: str
    provider_field: str
    bidirectional: bool = True


class ProviderMappingSpec(BaseModel):
    """The full mapping spec for one provider (Task 14.1)."""

    provider: str
    fields: list[FieldMapping] = Field(default_factory=list)

    def provider_field(self, canonical_field: str) -> str | None:
        for mapping in self.fields:
            if mapping.canonical_field == canonical_field:
                return mapping.provider_field
        return None


class IntegrationMapping(BaseModel):
    """Persisted internal<->external ID mapping (Task 14.4)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    work_item_id: WorkItemId
    provider: str
    external_id: str
    sync_state: SyncState = SyncState.PENDING
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None


class SyncConflict(BaseModel):
    """A detected disagreement between provider and brain (Task 14.5)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    work_item_id: WorkItemId
    provider: str
    external_id: str
    provider_field: str
    provider_value: str
    brain_value: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False


__all__ = [
    "FieldMapping",
    "IntegrationMapping",
    "ProviderMappingSpec",
    "SyncConflict",
    "SyncState",
]
