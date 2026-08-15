"""Shared building block for in-memory reference adapters.

A tiny thread-safe keyed collection.  This is a reference implementation for
contracts and tests only, never the production store.
"""

from __future__ import annotations

import threading
import uuid


class InMemoryCollection[T]:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[uuid.UUID, T] = {}

    async def upsert(self, item: T, item_id: uuid.UUID) -> T:
        with self._lock:
            self._items[item_id] = item
        return item

    async def get(self, item_id: uuid.UUID) -> T | None:
        with self._lock:
            return self._items.get(item_id)

    async def list_all(self) -> list[T]:
        with self._lock:
            return list(self._items.values())

    async def delete(self, item_id: uuid.UUID) -> None:
        with self._lock:
            self._items.pop(item_id, None)

    def _snapshot(self) -> list[T]:
        with self._lock:
            return list(self._items.values())
