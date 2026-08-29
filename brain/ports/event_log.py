"""Event log port.

The event log records every processed canonical event so operational chains
can be traced end-to-end through one ``correlation_id`` (webhook -> ingestion
-> context -> execution -> verification).
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from brain.domain.events import EventEnvelope


@runtime_checkable
class EventLogRepository(Protocol):
    async def append(self, event: EventEnvelope) -> None: ...

    async def list_by_correlation(self, correlation_id: uuid.UUID) -> list[EventEnvelope]: ...

    async def list_recent(self, limit: int = 100) -> list[EventEnvelope]: ...
