"""In-memory artifact store reference implementation."""

from __future__ import annotations

import threading


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        del content_type
        with self._lock:
            self._blobs[key] = data
        return key

    async def get(self, key: str) -> bytes:
        with self._lock:
            return self._blobs[key]

    async def delete(self, key: str) -> None:
        with self._lock:
            self._blobs.pop(key, None)
