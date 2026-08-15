"""In-memory idempotency store reference implementation."""

from __future__ import annotations

import uuid


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._processed: set[str] = set()

    async def is_processed(self, key: str) -> bool:
        return key in self._processed

    async def mark_processed(self, key: str, event_id: uuid.UUID | None = None) -> None:
        self._processed.add(key)
