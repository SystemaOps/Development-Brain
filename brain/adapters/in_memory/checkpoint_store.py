"""In-memory checkpoint store reference implementation."""

from __future__ import annotations

import copy
import threading


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: dict[str, dict[str, object]] = {}

    async def save(self, key: str, state: dict[str, object]) -> None:
        with self._lock:
            self._state[key] = copy.deepcopy(state)

    async def load(self, key: str) -> dict[str, object] | None:
        with self._lock:
            state = self._state.get(key)
            return copy.deepcopy(state) if state is not None else None

    async def delete(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)
