"""EventLogRepository contract."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.events import EventEnvelope, EventType
from brain.domain.identity import new_project_id
from brain.ports.event_log import EventLogRepository


def _envelope(
    correlation_id: uuid.UUID, event_type: EventType = EventType.DOCUMENT_CHANGED
) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        project_id=new_project_id(),
        correlation_id=correlation_id,
        causation_id=uuid.uuid4(),
        source="test",
        idempotency_key="webhook-1",
        payload={"nested": {"a": 1}},
    )


class EventLogRepositoryContract:
    @pytest.fixture
    def event_log(self) -> EventLogRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, event_log: EventLogRepository) -> None:
        assert isinstance(event_log, EventLogRepository)

    async def test_append_round_trips_envelope(self, event_log: EventLogRepository) -> None:
        correlation_id = uuid.uuid4()
        event = _envelope(correlation_id)
        await event_log.append(event)
        chain = await event_log.list_by_correlation(correlation_id)
        assert chain == [event]

    async def test_list_by_correlation_filters(self, event_log: EventLogRepository) -> None:
        first = uuid.uuid4()
        second = uuid.uuid4()
        await event_log.append(_envelope(first))
        await event_log.append(_envelope(second))
        await event_log.append(_envelope(first, event_type=EventType.WORK_ITEM_CHANGED))
        assert len(await event_log.list_by_correlation(first)) == 2
        assert len(await event_log.list_by_correlation(second)) == 1

    async def test_list_recent_orders_chronologically(self, event_log: EventLogRepository) -> None:
        correlation_id = uuid.uuid4()
        events = [
            _envelope(correlation_id, event_type=EventType.WORK_ITEM_CREATED),
            _envelope(correlation_id, event_type=EventType.WORK_ITEM_CHANGED),
            _envelope(correlation_id, event_type=EventType.EXECUTION_COMPLETED),
        ]
        for event in events:
            await event_log.append(event)
        assert await event_log.list_recent() == events
        assert await event_log.list_recent(limit=2) == events[-2:]
