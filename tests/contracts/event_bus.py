"""EventBus contract."""

from __future__ import annotations

import pytest

from brain.domain.events import EventEnvelope, EventType
from brain.domain.identity import new_project_id
from brain.ports.event_bus import EventBus, EventHandler


class RecordingHandler(EventHandler):
    def __init__(self) -> None:
        self.received: list[EventEnvelope] = []

    async def handle(self, event: EventEnvelope) -> None:
        self.received.append(event)


class EventBusContract:
    @pytest.fixture
    def event_bus(self) -> EventBus:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, event_bus: EventBus) -> None:
        assert isinstance(event_bus, EventBus)

    async def test_subscribed_handler_receives_event(self, event_bus: EventBus) -> None:
        handler = RecordingHandler()
        await event_bus.subscribe(EventType.WORK_ITEM_CHANGED.value, handler)
        event = EventEnvelope(
            event_type=EventType.WORK_ITEM_CHANGED,
            project_id=new_project_id(),
            source="test",
        )
        await event_bus.publish(event)
        assert handler.received == [event]

    async def test_unsubscribed_handler_receives_nothing(self, event_bus: EventBus) -> None:
        handler = RecordingHandler()
        await event_bus.subscribe(EventType.WORK_ITEM_CHANGED.value, handler)
        await event_bus.unsubscribe(EventType.WORK_ITEM_CHANGED.value, handler)
        await event_bus.publish(
            EventEnvelope(event_type=EventType.WORK_ITEM_CHANGED, source="test")
        )
        assert handler.received == []

    async def test_handler_ignores_other_event_types(self, event_bus: EventBus) -> None:
        handler = RecordingHandler()
        await event_bus.subscribe(EventType.WORK_ITEM_CHANGED.value, handler)
        await event_bus.publish(
            EventEnvelope(event_type=EventType.EXECUTION_COMPLETED, source="test")
        )
        assert handler.received == []

    async def test_multiple_handlers_all_receive(self, event_bus: EventBus) -> None:
        first = RecordingHandler()
        second = RecordingHandler()
        await event_bus.subscribe(EventType.DOCUMENT_CHANGED.value, first)
        await event_bus.subscribe(EventType.DOCUMENT_CHANGED.value, second)
        event = EventEnvelope(event_type=EventType.DOCUMENT_CHANGED, source="test")
        await event_bus.publish(event)
        assert first.received == [event]
        assert second.received == [event]
