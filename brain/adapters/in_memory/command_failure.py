"""In-memory command failure repository reference implementation (Phase 25)."""

from __future__ import annotations

import uuid

from brain.domain.command_failure import CommandFailure


class InMemoryCommandFailureRepository:
    """In-memory storage for command failures."""

    def __init__(self) -> None:
        self._failures: list[CommandFailure] = []

    async def save(self, failure: CommandFailure) -> CommandFailure:
        self._failures.append(failure)
        return failure

    async def list_by_command(self, command_id: uuid.UUID) -> list[CommandFailure]:
        return [f for f in self._failures if f.command_id == command_id]

    async def list_recent(self, limit: int = 100) -> list[CommandFailure]:
        return self._failures[-limit:]
