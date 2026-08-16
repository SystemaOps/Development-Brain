"""Workflow orchestration ports (Phase 16).

``WorkflowCheckpointRepository`` persists :class:`WorkflowState` so a workflow
can crash and resume.  This is conceptually separate from domain execution
records (Task 16.4).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import WorkflowId
from brain.domain.workflow import WorkflowState


@runtime_checkable
class WorkflowCheckpointRepository(Protocol):
    async def save_checkpoint(self, state: WorkflowState) -> WorkflowState: ...

    async def load_checkpoint(self, workflow_id: WorkflowId) -> WorkflowState | None: ...

    async def delete_checkpoint(self, workflow_id: WorkflowId) -> None: ...

    async def list_checkpoints(self) -> list[WorkflowState]: ...


__all__ = ["WorkflowCheckpointRepository"]
