from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.enums import AgentExecutionStatus
from agent_core.models import AgentExecution
from agent_core.ports.executions import AgentExecutionStart


class SqlAlchemyAgentExecutionRecorder:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def start(
        self,
        *,
        project_id: UUID,
        agent_name: str,
        thread_id: str,
        trigger_event_id: str | None,
        config_snapshot: dict[str, Any],
    ) -> AgentExecutionStart:
        attempt_number = (
            int(
                await self.db.scalar(
                    select(func.max(AgentExecution.attempt_number)).where(
                        AgentExecution.thread_id == thread_id,
                        AgentExecution.agent_name == agent_name,
                    )
                )
                or 0
            )
            + 1
        )
        execution = AgentExecution(
            project_id=project_id,
            agent_name=agent_name,
            thread_id=thread_id,
            trigger_event_id=UUID(trigger_event_id) if trigger_event_id else None,
            attempt_number=attempt_number,
            status=AgentExecutionStatus.RUNNING.value,
            config_snapshot=config_snapshot,
            started_at=datetime.utcnow(),
        )
        self.db.add(execution)
        await self.db.flush()
        return AgentExecutionStart(
            execution_id=execution.id,
            attempt_number=attempt_number,
        )

    async def finish(
        self,
        execution_id: UUID,
        *,
        status: AgentExecutionStatus,
        error_summary: dict[str, Any] | None = None,
    ) -> None:
        execution = await self.db.get(AgentExecution, execution_id)
        if execution is None:
            raise KeyError(f"Agent execution not found: {execution_id}")

        execution.status = status.value
        execution.ended_at = datetime.utcnow()
        execution.error_summary = error_summary
        await self.db.flush()
