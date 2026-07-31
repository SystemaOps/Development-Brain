from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.agent_platform.agents.base.contracts import AgentResult
from agent_core.agent_platform.orchestration.contracts import PersistedAgentResult
from agent_core.agent_platform.runtime.execution_context import CheckpointIdentity
from agent_core.models import AgentPlatformCheckpointRecord, AgentPlatformResultRecord, now_utc


class SqlAlchemyAgentCheckpointStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def save(self, *, identity: CheckpointIdentity, state: Any) -> str:
        values = {
            "project_key": identity.project_id,
            "workflow_id": identity.workflow_id,
            "agent_type": identity.agent_type,
            "agent_instance_id": identity.agent_instance_id,
            "execution_id": identity.execution_id,
            "thread_id": identity.thread_id,
            "checkpoint_id": identity.checkpoint_id,
            "checkpoint_key": identity.key,
            "state_json": state,
            "updated_at": now_utc(),
        }
        stmt = (
            insert(AgentPlatformCheckpointRecord)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_agent_platform_checkpoints_identity",
                set_={
                    "checkpoint_key": values["checkpoint_key"],
                    "state_json": values["state_json"],
                    "updated_at": values["updated_at"],
                },
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return identity.checkpoint_id

    async def load(self, *, identity: CheckpointIdentity) -> Any | None:
        record = await self.db.scalar(
            select(AgentPlatformCheckpointRecord).where(
                AgentPlatformCheckpointRecord.project_key == identity.project_id,
                AgentPlatformCheckpointRecord.workflow_id == identity.workflow_id,
                AgentPlatformCheckpointRecord.agent_type == identity.agent_type,
                AgentPlatformCheckpointRecord.agent_instance_id == identity.agent_instance_id,
                AgentPlatformCheckpointRecord.execution_id == identity.execution_id,
                AgentPlatformCheckpointRecord.thread_id == identity.thread_id,
                AgentPlatformCheckpointRecord.checkpoint_id == identity.checkpoint_id,
            )
        )
        if record is None:
            return None
        return record.state_json


class SqlAlchemyAgentResultStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def persist(self, result: AgentResult) -> PersistedAgentResult:
        result_json = result.model_dump(mode="json")
        record = AgentPlatformResultRecord(
            execution_id=result.execution_id,
            project_key=result.project_id or "unknown",
            task_key=result.task_id,
            agent_type=result.agent_type,
            status=result.status.value,
            next_action=result.next_action.value if result.next_action else None,
            summary=result.summary,
            result_type=type(result).__name__,
            result_json=result_json,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return PersistedAgentResult(result_id=record.id, result=result)

    async def get_payload(self, result_id: UUID) -> dict[str, Any] | None:
        record = await self.db.get(AgentPlatformResultRecord, result_id)
        if record is None:
            return None
        return record.result_json
