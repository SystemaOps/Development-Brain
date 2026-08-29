"""ExecutionRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.actors import Actor
from brain.domain.executions import Execution, ExecutionStatus
from brain.domain.identity import new_workflow_id
from brain.domain.projects import Project
from brain.domain.work_items import WorkItem
from brain.ports.repositories import ExecutionRepository


class ExecutionRepositoryContract:
    @pytest.fixture
    def execution_repository(self) -> ExecutionRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, execution_repository: ExecutionRepository) -> None:
        assert isinstance(execution_repository, ExecutionRepository)

    async def test_create_and_get_round_trip(
        self, execution_repository: ExecutionRepository
    ) -> None:
        project = Project(name="auth")
        executor = Actor(actor_type="agent", display_name="pi")
        work_item = WorkItem(project_id=project.id, title="t")
        execution = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=work_item.id,
            executor_id=executor.id,
        )
        await execution_repository.create(execution)
        assert await execution_repository.get(execution.id) == execution

    async def test_update_status(self, execution_repository: ExecutionRepository) -> None:
        project = Project(name="auth")
        execution = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=WorkItem(project_id=project.id, title="t").id,
            executor_id=Actor(actor_type="agent", display_name="pi").id,
        )
        await execution_repository.create(execution)

        execution.status = ExecutionStatus.COMPLETED
        await execution_repository.update(execution)

        assert (await execution_repository.get(execution.id)).status == ExecutionStatus.COMPLETED

    async def test_multiple_executions_per_work_item(
        self, execution_repository: ExecutionRepository
    ) -> None:
        project = Project(name="auth")
        work_item_id = WorkItem(project_id=project.id, title="t").id
        executor_id = Actor(actor_type="agent", display_name="pi").id
        first = Execution(
            workflow_id=new_workflow_id(), work_item_id=work_item_id, executor_id=executor_id
        )
        second = Execution(
            workflow_id=new_workflow_id(), work_item_id=work_item_id, executor_id=executor_id
        )
        await execution_repository.create(first)
        await execution_repository.create(second)

        executions = await execution_repository.list_by_work_item(work_item_id)
        assert {e.id for e in executions} == {first.id, second.id}
        assert first.id != second.id
