from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.models import OpenProjectOutboundOperation
from agent_core.ports.openproject import (
    OpenProjectOperationClaim,
    OpenProjectOperationStatus,
    OpenProjectOperationType,
)


class SqlAlchemyOpenProjectOutboundStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def claim_operation(
        self,
        *,
        idempotency_key: str,
        operation_type: OpenProjectOperationType,
        request_payload: dict,
        project_id: UUID | None = None,
        artifact_id: UUID | None = None,
        target_artifact_type: str | None = None,
        target_external_id: str | None = None,
    ) -> OpenProjectOperationClaim:
        stmt = (
            insert(OpenProjectOutboundOperation)
            .values(
                idempotency_key=idempotency_key,
                operation_type=operation_type.value,
                status=OpenProjectOperationStatus.PENDING.value,
                project_id=project_id,
                artifact_id=artifact_id,
                target_artifact_type=target_artifact_type,
                target_external_id=target_external_id,
                request_payload=request_payload,
            )
            .on_conflict_do_nothing(
                index_elements=[OpenProjectOutboundOperation.idempotency_key]
            )
            .returning(OpenProjectOutboundOperation.id)
        )

        inserted_id = await self.db.scalar(stmt)
        if inserted_id is not None:
            await self.db.commit()
            return OpenProjectOperationClaim(
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                status=OpenProjectOperationStatus.PENDING,
                should_execute=True,
            )

        existing = await self.db.scalar(
            select(OpenProjectOutboundOperation).where(
                OpenProjectOutboundOperation.idempotency_key == idempotency_key
            ).with_for_update()
        )
        if existing is None:
            await self.db.rollback()
            raise RuntimeError(
                "OpenProject outbound operation conflict did not find existing record"
            )
        if existing.operation_type != operation_type.value:
            await self.db.rollback()
            raise RuntimeError(
                "OpenProject idempotency key was reused for a different operation type"
            )
        if existing.status == OpenProjectOperationStatus.FAILED.value:
            existing.status = OpenProjectOperationStatus.PENDING.value
            existing.project_id = project_id
            existing.artifact_id = artifact_id
            existing.target_artifact_type = target_artifact_type
            existing.target_external_id = target_external_id
            existing.request_payload = request_payload
            existing.response_payload = None
            existing.error_message = None
            existing.completed_at = None
            await self.db.commit()
            return OpenProjectOperationClaim(
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                status=OpenProjectOperationStatus.PENDING,
                should_execute=True,
                reclaimed=True,
            )

        claim = OpenProjectOperationClaim(
            idempotency_key=idempotency_key,
            operation_type=OpenProjectOperationType(existing.operation_type),
            status=OpenProjectOperationStatus(existing.status),
            should_execute=False,
            response_payload=existing.response_payload,
            error_message=existing.error_message,
        )
        await self.db.rollback()
        return claim

    async def mark_succeeded(
        self,
        *,
        idempotency_key: str,
        response_payload: dict,
    ) -> None:
        operation = await self._require_operation(idempotency_key)
        operation.status = OpenProjectOperationStatus.SUCCEEDED.value
        operation.response_payload = response_payload
        operation.error_message = None
        operation.completed_at = datetime.utcnow()
        await self.db.commit()

    async def mark_failed(
        self,
        *,
        idempotency_key: str,
        error_message: str,
    ) -> None:
        operation = await self._require_operation(idempotency_key)
        operation.status = OpenProjectOperationStatus.FAILED.value
        operation.error_message = error_message[:2000]
        operation.completed_at = datetime.utcnow()
        await self.db.commit()

    async def _require_operation(self, idempotency_key: str) -> OpenProjectOutboundOperation:
        operation = await self.db.scalar(
            select(OpenProjectOutboundOperation).where(
                OpenProjectOutboundOperation.idempotency_key == idempotency_key
            )
        )
        if operation is None:
            raise KeyError(f"OpenProject outbound operation not found: {idempotency_key}")
        return operation
