"""Work-management integration persistence port (Phase 14).

Persists the internal<->external ID mapping (Task 14.4) and sync conflicts
(Task 14.5) so provider swaps never lose the linkage.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import WorkItemId
from brain.domain.work_management import IntegrationMapping, SyncConflict


@runtime_checkable
class WorkManagementIntegrationRepository(Protocol):
    async def save_mapping(self, mapping: IntegrationMapping) -> IntegrationMapping: ...

    async def get_mapping(
        self, work_item_id: WorkItemId, provider: str
    ) -> IntegrationMapping | None: ...

    async def list_mappings(self, work_item_id: WorkItemId) -> list[IntegrationMapping]: ...

    async def save_conflict(self, conflict: SyncConflict) -> SyncConflict: ...

    async def list_conflicts(self, work_item_id: WorkItemId) -> list[SyncConflict]: ...


__all__ = ["WorkManagementIntegrationRepository"]
