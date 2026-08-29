"""Context capsule persistence port (Task 10.10).

Stores built context capsules (version, inputs, selected entities, scores,
token counts, model budget, repository revision) so later evaluation can
inspect what context was constructed and why.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.context import ContextCapsule
from brain.domain.identity import ContextCapsuleId, WorkItemId


@runtime_checkable
class ContextCapsuleRepository(Protocol):
    async def save_capsule(self, capsule: ContextCapsule) -> ContextCapsule: ...

    async def get_capsule(self, capsule_id: ContextCapsuleId) -> ContextCapsule | None: ...

    async def list_capsules_for_work_item(
        self, work_item_id: WorkItemId
    ) -> list[ContextCapsule]: ...

    async def delete_capsule(self, capsule_id: ContextCapsuleId) -> None: ...


__all__ = ["ContextCapsuleRepository"]
