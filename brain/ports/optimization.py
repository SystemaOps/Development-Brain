"""Optimization ports (Phase 20).

``ExecutorQualityRepository`` tracks per-task-type quality per executor so the
router can choose based on demonstrated performance instead of one global
"best model" score (Task 20.5).  ``ContextFeedbackRepository`` stores ranking
feedback so weights can be adjusted from historical outcomes (Task 20.3).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import ActorId, WorkItemId
from brain.domain.optimization import (
    ContextFeedbackRecord,
    ExecutorQualityEntry,
)


@runtime_checkable
class ExecutorQualityRepository(Protocol):
    async def save_entry(self, entry: ExecutorQualityEntry) -> ExecutorQualityEntry: ...

    async def get_entry(
        self, executor_id: ActorId, task_type: str
    ) -> ExecutorQualityEntry | None: ...

    async def list_for_executor(self, executor_id: ActorId) -> list[ExecutorQualityEntry]: ...

    async def list_by_task_type(self, task_type: str) -> list[ExecutorQualityEntry]: ...


@runtime_checkable
class ContextFeedbackRepository(Protocol):
    async def save_feedback(self, record: ContextFeedbackRecord) -> ContextFeedbackRecord: ...

    async def list_recent(
        self, work_item_id: WorkItemId | None = None, limit: int = 100
    ) -> list[ContextFeedbackRecord]: ...


__all__ = ["ContextFeedbackRepository", "ExecutorQualityRepository"]
