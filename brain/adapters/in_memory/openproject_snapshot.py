"""In-memory OpenProject snapshot store (reference adapter)."""

from __future__ import annotations

import threading

from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.ports.openproject_snapshot import OpenProjectSnapshotStore


class InMemoryOpenProjectSnapshotStore(OpenProjectSnapshotStore):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots: dict[str, OpenProjectWorkItemSnapshot] = {}

    async def get(self, external_id: str) -> OpenProjectWorkItemSnapshot | None:
        with self._lock:
            return self._snapshots.get(external_id)

    async def save(self, snapshot: OpenProjectWorkItemSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.external_id] = snapshot


__all__ = ["InMemoryOpenProjectSnapshotStore"]
