"""Command queue port (Phase 24).

``CommandQueue`` is the queue abstraction for long-running commands.  An
in-memory implementation serves unit tests and local development; Redis is the
production implementation.  Dead-letter / failure semantics stay behind this
port so the orchestrator never depends on a specific queue.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from brain.domain.commands import CommandEnvelope


@runtime_checkable
class CommandQueue(Protocol):
    async def enqueue(self, command: CommandEnvelope) -> None: ...

    async def consume(self, timeout_seconds: float = 1.0) -> CommandEnvelope | None: ...

    async def acknowledge(self, command_id: uuid.UUID) -> None: ...

    async def requeue(self, command: CommandEnvelope, *, delay_seconds: float = 0.0) -> None: ...

    async def dead_letter(self, command: CommandEnvelope, reason: str) -> None: ...

    async def pending_count(self) -> int: ...

    async def close(self) -> None: ...


__all__ = ["CommandQueue"]
