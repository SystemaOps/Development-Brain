"""In-memory event log reference implementation."""

from __future__ import annotations

import uuid

from brain.domain.events import EventEnvelope


class InMemoryEventLogRepository:
    def __init__(self) -> None:
        self._events: list[EventEnvelope] = []

    async def append(self, event: EventEnvelope) -> None:
        self._events.append(event)

    async def list_by_correlation(self, correlation_id: uuid.UUID) -> list[EventEnvelope]:
        return [e for e in self._events if e.correlation_id == correlation_id]

    async def list_recent(self, limit: int = 100) -> list[EventEnvelope]:
        return self._events[-limit:]
