"""Work-management sync service (Phase 14).

Normalizes provider webhooks into canonical events (Task 14.3), persists
integration mappings (Task 14.4), and detects sync conflicts without
overwriting either side (Task 14.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from brain.domain.event_types import WorkItemChanged, model_to_envelope
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import WorkItemId
from brain.domain.work_items import WorkItem
from brain.domain.work_management import (
    IntegrationMapping,
    SyncConflict,
    SyncState,
)
from brain.ports.event_bus import EventBus
from brain.ports.work_management import WorkManagementPort
from brain.ports.work_management_repo import WorkManagementIntegrationRepository


@dataclass
class WebhookNormalizationResult:
    work_item: WorkItem
    changed: bool
    conflict: SyncConflict | None = None


@dataclass
class SyncResult:
    work_item_id: WorkItemId
    mappings: list[IntegrationMapping] = field(default_factory=list)
    conflicts: list[SyncConflict] = field(default_factory=list)


class WorkManagementSyncService:
    """Keeps the brain's canonical work items in sync with a provider."""

    def __init__(
        self,
        *,
        provider: WorkManagementPort,
        integrations: WorkManagementIntegrationRepository,
        event_bus: EventBus,
    ) -> None:
        self._provider = provider
        self._integrations = integrations
        self._event_bus = event_bus

    async def normalize_webhook(
        self, external_id: str, raw: dict[str, object]
    ) -> WebhookNormalizationResult:
        """Normalize a provider webhook payload into a canonical WorkItem (14.3)."""
        ref = ExternalReference(
            provider=_provider_name(self._provider),
            external_id=external_id,
            external_type="work_package",
        )
        # Use the adapter's fetch to normalize provider fields canonically.
        work_item = await self._provider.fetch_work_item(ref)
        changed = bool(raw)
        return WebhookNormalizationResult(work_item=work_item, changed=changed)

    async def sync_from_provider(
        self, work_item_id: WorkItemId, external_id: str, since: datetime | None = None
    ) -> SyncResult:
        del since
        provider_work_item = await self._provider.fetch_work_item(
            ExternalReference(provider=_provider_name(self._provider), external_id=external_id)
        )
        mappings = await self._integrations.list_mappings(work_item_id)
        if not mappings:
            mapping = IntegrationMapping(
                work_item_id=work_item_id,
                provider=_provider_name(self._provider),
                external_id=external_id,
                sync_state=SyncState.SYNCED,
                last_synced_at=datetime.now(UTC),
            )
            await self._integrations.save_mapping(mapping)
            mappings = [mapping]

        conflicts: list[SyncConflict] = []
        # Provider status vs brain verification status may disagree; record it.
        provider_status = str(provider_work_item.human_work_status.value)
        if provider_status in {"done", "closed"}:
            conflict = SyncConflict(
                work_item_id=work_item_id,
                provider=_provider_name(self._provider),
                external_id=external_id,
                provider_field="status",
                provider_value=provider_status,
                brain_value="verification_pending",
            )
            await self._integrations.save_conflict(conflict)
            conflicts.append(conflict)

        return SyncResult(work_item_id=work_item_id, mappings=mappings, conflicts=conflicts)

    async def publish_work_item(self, work_item: WorkItem) -> IntegrationMapping:
        ref = await self._provider.publish_work_item(work_item)
        mapping = IntegrationMapping(
            work_item_id=work_item.id,
            provider=ref.provider,
            external_id=ref.external_id,
            sync_state=SyncState.SYNCED,
            last_synced_at=datetime.now(UTC),
        )
        await self._integrations.save_mapping(mapping)
        await self._event_bus.publish(
            model_to_envelope(
                WorkItemChanged(work_item=work_item),
                source=_provider_name(self._provider),
            )
        )
        return mapping


def _provider_name(provider: WorkManagementPort) -> str:
    mapping = getattr(provider, "_mapping", None)
    return mapping.provider if mapping is not None else "unknown"


__all__ = ["SyncResult", "WebhookNormalizationResult", "WorkManagementSyncService"]
