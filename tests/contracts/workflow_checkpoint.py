"""WorkflowCheckpointRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.workflow import WorkflowStage, WorkflowState
from brain.ports.workflow import WorkflowCheckpointRepository


def _state() -> WorkflowState:
    return WorkflowState(stage=WorkflowStage.BUILD_CONTEXT, retry_count=1)


class WorkflowCheckpointRepositoryContract:
    @pytest.fixture
    def workflow_checkpoints(self) -> WorkflowCheckpointRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(
        self, workflow_checkpoints: WorkflowCheckpointRepository
    ) -> None:
        assert isinstance(workflow_checkpoints, WorkflowCheckpointRepository)

    async def test_save_and_load_round_trip(
        self, workflow_checkpoints: WorkflowCheckpointRepository
    ) -> None:
        state = _state()
        await workflow_checkpoints.save_checkpoint(state)
        stored = await workflow_checkpoints.load_checkpoint(state.workflow_id)
        assert stored is not None
        assert stored.stage == WorkflowStage.BUILD_CONTEXT
        assert stored.retry_count == 1

    async def test_load_missing_returns_none(
        self, workflow_checkpoints: WorkflowCheckpointRepository
    ) -> None:
        assert await workflow_checkpoints.load_checkpoint(_state().workflow_id) is None

    async def test_delete(self, workflow_checkpoints: WorkflowCheckpointRepository) -> None:
        state = _state()
        await workflow_checkpoints.save_checkpoint(state)
        await workflow_checkpoints.delete_checkpoint(state.workflow_id)
        assert await workflow_checkpoints.load_checkpoint(state.workflow_id) is None

    async def test_list_checkpoints(
        self, workflow_checkpoints: WorkflowCheckpointRepository
    ) -> None:
        await workflow_checkpoints.save_checkpoint(_state())
        assert len(await workflow_checkpoints.list_checkpoints()) >= 1
