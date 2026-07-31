from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from agent_core.domain.enums import AgentExecutionStatus
from agent_core.models import AgentExecution
from agent_core.persistence.executions import SqlAlchemyAgentExecutionRecorder


class FakeExecutionSession:
    def __init__(self, scalar_result=0):
        self.scalar_result = scalar_result
        self.added: list[AgentExecution] = []
        self.flushed = 0
        self.by_id: dict[UUID, AgentExecution] = {}

    async def scalar(self, statement):
        self.statement = statement
        return self.scalar_result

    def add(self, item):
        if item.id is None:
            item.id = uuid4()
        self.added.append(item)
        self.by_id[item.id] = item

    async def flush(self):
        self.flushed += 1

    async def get(self, model, item_id):
        assert model is AgentExecution
        return self.by_id.get(item_id)


@pytest.mark.asyncio
async def test_agent_execution_recorder_starts_incremented_attempt():
    project_id = uuid4()
    event_id = uuid4()
    session = FakeExecutionSession(scalar_result=2)
    recorder = SqlAlchemyAgentExecutionRecorder(session)

    result = await recorder.start(
        project_id=project_id,
        agent_name="planning",
        thread_id="planning-session-1",
        trigger_event_id=str(event_id),
        config_snapshot={"workflow": "planning"},
    )

    execution = session.added[0]
    assert result.execution_id == execution.id
    assert result.attempt_number == 3
    assert execution.project_id == project_id
    assert execution.agent_name == "planning"
    assert execution.thread_id == "planning-session-1"
    assert execution.trigger_event_id == event_id
    assert execution.attempt_number == 3
    assert execution.status == AgentExecutionStatus.RUNNING.value
    assert execution.config_snapshot == {"workflow": "planning"}
    assert execution.started_at is not None
    assert session.flushed == 1


@pytest.mark.asyncio
async def test_agent_execution_recorder_finishes_execution_with_error_summary():
    session = FakeExecutionSession()
    execution = AgentExecution(
        id=uuid4(),
        project_id=uuid4(),
        agent_name="planning",
        thread_id="planning-session-1",
        attempt_number=1,
        status=AgentExecutionStatus.RUNNING.value,
        config_snapshot={},
    )
    session.by_id[execution.id] = execution
    recorder = SqlAlchemyAgentExecutionRecorder(session)

    await recorder.finish(
        execution.id,
        status=AgentExecutionStatus.FAILED,
        error_summary={"message": "timed out"},
    )

    assert execution.status == AgentExecutionStatus.FAILED.value
    assert execution.error_summary == {"message": "timed out"}
    assert execution.ended_at is not None
    assert session.flushed == 1
