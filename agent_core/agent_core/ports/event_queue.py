from __future__ import annotations

from typing import Protocol


class EventQueuePort(Protocol):
    async def enqueue(self, event_id: str) -> None:
        ...

    async def dequeue(self, *, timeout_seconds: int = 5) -> str | None:
        ...
