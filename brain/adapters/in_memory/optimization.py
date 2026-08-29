"""In-memory optimization reference adapters (Phase 20)."""

from __future__ import annotations

from brain.domain.identity import ActorId, WorkItemId
from brain.domain.optimization import (
    ContextFeedbackRecord,
    ExecutorQualityEntry,
)


class InMemoryExecutorQualityRepository:
    """In-memory per-task-type quality tracking."""

    def __init__(self) -> None:
        self._entries: dict[tuple[ActorId, str], ExecutorQualityEntry] = {}

    async def save_entry(self, entry: ExecutorQualityEntry) -> ExecutorQualityEntry:
        self._entries[(entry.executor_id, entry.task_type)] = entry
        return entry

    async def get_entry(self, executor_id: ActorId, task_type: str) -> ExecutorQualityEntry | None:
        return self._entries.get((executor_id, task_type))

    async def list_for_executor(self, executor_id: ActorId) -> list[ExecutorQualityEntry]:
        return [e for (eid, _), e in self._entries.items() if eid == executor_id]

    async def list_by_task_type(self, task_type: str) -> list[ExecutorQualityEntry]:
        return [e for (_, t), e in self._entries.items() if t == task_type]


class InMemoryContextFeedbackRepository:
    """In-memory ranking feedback store."""

    def __init__(self) -> None:
        self._records: list[ContextFeedbackRecord] = []

    async def save_feedback(self, record: ContextFeedbackRecord) -> ContextFeedbackRecord:
        self._records.append(record)
        return record

    async def list_recent(
        self, work_item_id: WorkItemId | None = None, limit: int = 100
    ) -> list[ContextFeedbackRecord]:
        records = self._records
        if work_item_id is not None:
            records = [r for r in records if r.work_item_id == work_item_id]
        return records[-limit:]
