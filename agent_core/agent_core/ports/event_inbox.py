from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.events import EventEnvelope


@dataclass(frozen=True)
class EventInboxPersistResult:
    event_id: str
    created: bool


class EventInboxPort(Protocol):
    async def persist(self, envelope: EventEnvelope) -> EventInboxPersistResult:
        ...

    async def get(self, event_id: str) -> EventEnvelope | None:
        ...

    async def mark_processing(self, event_id: str) -> None:
        ...

    async def mark_processed(self, event_id: str) -> None:
        ...

    async def mark_failed(self, event_id: str, message: str) -> None:
        ...
