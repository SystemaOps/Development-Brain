from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.events import EventEnvelope
from agent_core.models import AgentJob, WebhookEvent
from agent_core.ports.event_inbox import EventInboxPersistResult


class SqlAlchemyEventInbox:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def persist(self, envelope: EventEnvelope) -> EventInboxPersistResult:
        event_id = uuid4()
        stmt = (
            insert(WebhookEvent)
            .values(
                id=event_id,
                idempotency_key=envelope.idempotency_key,
                source_tool=envelope.source,
                event_type=envelope.event_type,
                external_project_id=envelope.external_project_id,
                external_work_package_id=envelope.external_work_package_id,
                external_comment_id=envelope.external_comment_id,
                headers=envelope.headers,
                payload=envelope.payload,
                processing_status="pending",
            )
            .on_conflict_do_nothing(index_elements=[WebhookEvent.idempotency_key])
            .returning(WebhookEvent.id)
        )
        inserted_id = await self.db.scalar(stmt)

        if inserted_id is not None:
            self.db.add(AgentJob(event_id=inserted_id, job_type="process_pm_event"))
            await self.db.commit()
            return EventInboxPersistResult(event_id=str(inserted_id), created=True)

        existing_id = await self.db.scalar(
            select(WebhookEvent.id).where(
                WebhookEvent.idempotency_key == envelope.idempotency_key
            )
        )
        if existing_id is None:
            raise RuntimeError("Webhook event conflict resolution did not find existing event")

        await self.db.rollback()
        return EventInboxPersistResult(event_id=str(existing_id), created=False)

    async def get(self, event_id: str) -> EventEnvelope | None:
        event = await self.db.get(WebhookEvent, UUID(event_id))
        if event is None:
            return None
        return EventEnvelope(
            source=event.source_tool,
            event_type=event.event_type,
            idempotency_key=event.idempotency_key,
            payload=event.payload,
            headers=event.headers,
            external_project_id=event.external_project_id,
            external_work_package_id=event.external_work_package_id,
            external_comment_id=event.external_comment_id,
        )

    async def mark_processing(self, event_id: str) -> None:
        event = await self._require_event(event_id)
        event.processing_status = "processing"
        event.retry_count += 1
        await self._set_latest_job_status(event.id, "running", started_at=datetime.utcnow())
        await self.db.commit()

    async def mark_processed(self, event_id: str) -> None:
        event = await self._require_event(event_id)
        event.processing_status = "processed"
        event.processed_at = datetime.utcnow()
        event.error_message = None
        await self._set_latest_job_status(event.id, "done", finished_at=datetime.utcnow())
        await self.db.commit()

    async def mark_failed(self, event_id: str, message: str) -> None:
        event = await self._require_event(event_id)
        event.processing_status = "failed"
        event.error_message = message[:2000]
        await self._set_latest_job_status(
            event.id,
            "failed",
            finished_at=datetime.utcnow(),
            error_message=message[:2000],
        )
        await self.db.commit()

    async def _require_event(self, event_id: str) -> WebhookEvent:
        event = await self.db.get(WebhookEvent, UUID(event_id))
        if event is None:
            raise KeyError(f"Webhook event not found: {event_id}")
        return event

    async def _set_latest_job_status(
        self,
        event_id: UUID,
        status: str,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        job = await self.db.scalar(
            select(AgentJob)
            .where(AgentJob.event_id == event_id)
            .order_by(AgentJob.created_at.desc())
            .limit(1)
        )
        if job is None:
            return
        job.status = status
        if started_at is not None:
            job.started_at = started_at
        if finished_at is not None:
            job.finished_at = finished_at
        if error_message is not None:
            job.error_message = error_message
