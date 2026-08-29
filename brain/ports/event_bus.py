"""Event bus port.

Canonical events are published on the bus; handlers subscribe by event type.
Redis is one implementation; in-memory is another.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.events import EventEnvelope


@runtime_checkable
class EventHandler(Protocol):
    async def handle(self, event: EventEnvelope) -> None: ...


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: EventEnvelope) -> None: ...

    async def subscribe(self, event_type: str, handler: EventHandler) -> None: ...

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None: ...
