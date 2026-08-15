"""Checkpoint store port.

Workflow checkpoints answer "where should orchestration resume".  This is a
different concept from the domain Execution record ("what engineering work
happened"), and the two stay separate.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, key: str, state: dict[str, object]) -> None: ...

    async def load(self, key: str) -> dict[str, object] | None: ...

    async def delete(self, key: str) -> None: ...
