"""Command failure persistence port (Phase 25)."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from brain.domain.command_failure import CommandFailure


@runtime_checkable
class CommandFailureRepository(Protocol):
    async def save(self, failure: CommandFailure) -> CommandFailure: ...

    async def list_by_command(self, command_id: uuid.UUID) -> list[CommandFailure]: ...

    async def list_recent(self, limit: int = 100) -> list[CommandFailure]: ...


__all__ = ["CommandFailureRepository"]
