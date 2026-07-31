from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.models import OpenProjectReconciliationSnapshot
from agent_core.ports.openproject import OpenProjectOperationType


class SqlAlchemyOpenProjectReconciliationStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_snapshot(
        self,
        *,
        outbound_idempotency_key: str,
        operation_type: OpenProjectOperationType,
        target_artifact_type: str,
        target_external_id: str,
        before_payload: dict,
        agent_payload: dict,
        before_activities_payload: dict | None = None,
        detected_human_edits: list[dict] | None = None,
        project_id: UUID | None = None,
        artifact_id: UUID | None = None,
    ) -> None:
        self.db.add(
            OpenProjectReconciliationSnapshot(
                project_id=project_id,
                artifact_id=artifact_id,
                outbound_idempotency_key=outbound_idempotency_key,
                operation_type=operation_type.value,
                target_artifact_type=target_artifact_type,
                target_external_id=target_external_id,
                before_payload=before_payload,
                before_activities_payload=before_activities_payload,
                agent_payload=agent_payload,
                detected_human_edits=detected_human_edits or [],
            )
        )
        await self.db.commit()
