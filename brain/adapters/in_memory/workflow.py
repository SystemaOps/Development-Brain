"""In-memory workflow checkpoint repository reference implementation."""

from __future__ import annotations

from brain.domain.identity import WorkflowId
from brain.domain.workflow import WorkflowState


class InMemoryWorkflowCheckpointRepository:
    """In-memory storage for workflow checkpoints."""

    def __init__(self) -> None:
        self._checkpoints: dict[WorkflowId, WorkflowState] = {}

    async def save_checkpoint(self, state: WorkflowState) -> WorkflowState:
        self._checkpoints[state.workflow_id] = state
        return state

    async def load_checkpoint(self, workflow_id: WorkflowId) -> WorkflowState | None:
        return self._checkpoints.get(workflow_id)

    async def delete_checkpoint(self, workflow_id: WorkflowId) -> None:
        self._checkpoints.pop(workflow_id, None)

    async def list_checkpoints(self) -> list[WorkflowState]:
        return list(self._checkpoints.values())
