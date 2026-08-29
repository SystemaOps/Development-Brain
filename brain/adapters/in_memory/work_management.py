"""In-memory work-management integration repository."""

from __future__ import annotations

from brain.domain.identity import WorkItemId
from brain.domain.work_management import IntegrationMapping, SyncConflict


class InMemoryWorkManagementIntegrationRepository:
    """In-memory storage for provider mappings and sync conflicts."""

    def __init__(self) -> None:
        self._mappings: dict[str, IntegrationMapping] = {}
        self._conflicts: list[SyncConflict] = []

    async def save_mapping(self, mapping: IntegrationMapping) -> IntegrationMapping:
        key = f"{mapping.work_item_id}:{mapping.provider}"
        self._mappings[key] = mapping
        return mapping

    async def get_mapping(
        self, work_item_id: WorkItemId, provider: str
    ) -> IntegrationMapping | None:
        return self._mappings.get(f"{work_item_id}:{provider}")

    async def list_mappings(self, work_item_id: WorkItemId) -> list[IntegrationMapping]:
        return [m for m in self._mappings.values() if m.work_item_id == work_item_id]

    async def save_conflict(self, conflict: SyncConflict) -> SyncConflict:
        self._conflicts.append(conflict)
        return conflict

    async def list_conflicts(self, work_item_id: WorkItemId) -> list[SyncConflict]:
        return [c for c in self._conflicts if c.work_item_id == work_item_id]
