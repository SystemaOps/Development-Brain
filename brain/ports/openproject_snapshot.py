"""OpenProject snapshot store port.

Normalized work-item snapshots are kept per external id so that an incoming
webhook can be diffed against the previous snapshot (doc §14).  The store is
adapter-agnostic: in-memory for the reference runtime, PostgreSQL later.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.application.openproject_parser import OpenProjectWorkItemSnapshot


@runtime_checkable
class OpenProjectSnapshotStore(Protocol):
    async def get(self, external_id: str) -> OpenProjectWorkItemSnapshot | None: ...

    async def save(self, snapshot: OpenProjectWorkItemSnapshot) -> None: ...


__all__ = ["OpenProjectSnapshotStore"]
