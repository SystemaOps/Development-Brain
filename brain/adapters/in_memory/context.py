"""In-memory context capsule repository reference implementation."""

from __future__ import annotations

from brain.domain.context import ContextCapsule
from brain.domain.identity import ContextCapsuleId, WorkItemId


class InMemoryContextCapsuleRepository:
    """In-memory storage for built context capsules."""

    def __init__(self) -> None:
        self._capsules: dict[ContextCapsuleId, ContextCapsule] = {}

    async def save_capsule(self, capsule: ContextCapsule) -> ContextCapsule:
        self._capsules[capsule.id] = capsule
        return capsule

    async def get_capsule(self, capsule_id: ContextCapsuleId) -> ContextCapsule | None:
        return self._capsules.get(capsule_id)

    async def list_capsules_for_work_item(self, work_item_id: WorkItemId) -> list[ContextCapsule]:
        return [c for c in self._capsules.values() if c.work_item_id == work_item_id]

    async def delete_capsule(self, capsule_id: ContextCapsuleId) -> None:
        self._capsules.pop(capsule_id, None)
