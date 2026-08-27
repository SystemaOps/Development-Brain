"""In-memory command queue (Phase 24).

Reference implementation of :class:`CommandQueue` for unit tests and local
development without Redis.
"""

from __future__ import annotations

import asyncio
import uuid

from brain.domain.commands import CommandEnvelope


class InMemoryCommandQueue:
    """FIFO command queue in process memory."""

    def __init__(self) -> None:
        self._pending: list[CommandEnvelope] = []
        self._inflight: dict[uuid.UUID, CommandEnvelope] = {}
        self._dead: list[tuple[CommandEnvelope, str]] = []
        self._condition = asyncio.Condition()

    async def enqueue(self, command: CommandEnvelope) -> None:
        async with self._condition:
            self._pending.append(command)
            self._condition.notify_all()

    async def consume(self, timeout_seconds: float = 1.0) -> CommandEnvelope | None:
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: bool(self._pending)),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                return None
            command = self._pending.pop(0)
            self._inflight[command.command_id] = command
            return command

    async def acknowledge(self, command_id: uuid.UUID) -> None:
        self._inflight.pop(command_id, None)

    async def requeue(self, command: CommandEnvelope, *, delay_seconds: float = 0.0) -> None:
        self._inflight.pop(command.command_id, None)
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        await self.enqueue(command)

    async def dead_letter(self, command: CommandEnvelope, reason: str) -> None:
        self._inflight.pop(command.command_id, None)
        self._dead.append((command, reason))

    async def pending_count(self) -> int:
        return len(self._pending)

    async def close(self) -> None:
        self._pending.clear()
        self._inflight.clear()

    def dead_letters(self) -> list[tuple[CommandEnvelope, str]]:
        return list(self._dead)
