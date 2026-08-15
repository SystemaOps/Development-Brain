"""In-memory event bus reference implementation."""

from __future__ import annotations

import threading

from brain.domain.events import EventEnvelope
from brain.ports.event_bus import EventHandler


class InMemoryEventBus:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, list[EventHandler]] = {}
        self.published: list[EventEnvelope] = []

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        with self._lock:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    async def publish(self, event: EventEnvelope) -> None:
        self.published.append(event)
        with self._lock:
            handlers = list(self._handlers.get(event.event_type.value, []))
        for handler in handlers:
            await handler.handle(event)
