"""Command dispatcher (Phase 24).

Maps canonical command types to handler callables.  The dispatcher contains no
business logic: it routes an envelope to the registered handler for its
command type.  The same dispatcher is used by the in-process local executor
(unit tests) and by the worker runtime.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from brain.domain.commands import (
    CommandEnvelope,
    CommandType,
)

logger = logging.getLogger(__name__)

CommandHandler = Callable[[CommandEnvelope], Awaitable[object]]


class CommandDispatcher:
    """Routes command envelopes to registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[CommandType, CommandHandler] = {}

    def register(self, command_type: CommandType, handler: CommandHandler) -> None:
        self._handlers[command_type] = handler

    def unregister(self, command_type: CommandType) -> None:
        self._handlers.pop(command_type, None)

    def has_handler(self, command_type: CommandType) -> bool:
        return command_type in self._handlers

    async def dispatch(self, command: CommandEnvelope) -> object:
        handler = self._handlers.get(command.command_type)
        if handler is None:
            raise CommandHandlerNotFound(command.command_type)
        return await handler(command)


class CommandHandlerNotFound(Exception):
    def __init__(self, command_type: CommandType) -> None:
        super().__init__(f"no handler for command {command_type.value}")
        self.command_type = command_type


def run_command_loop(
    dispatcher: CommandDispatcher,
    queue: Any,
    *,
    max_commands: int | None = None,
) -> Callable[[], Awaitable[int]]:
    """Return an async loop function consuming commands until the queue empties.

    Used by unit tests and local development; the worker uses its own loop with
    signal handling.  Handlers are wrapped so an exception fails the command
    without crashing the loop.
    """

    async def _run() -> int:
        processed = 0
        while max_commands is None or processed < max_commands:
            command = await queue.consume(timeout_seconds=0.1)
            if command is None:
                break
            try:
                await dispatcher.dispatch(command)
                await queue.acknowledge(command.command_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("command %s failed: %s", command.command_type.value, exc)
                await queue.dead_letter(command, str(exc))
            processed += 1
        return processed

    return _run


__all__ = [
    "CommandDispatcher",
    "CommandHandler",
    "CommandHandlerNotFound",
    "run_command_loop",
]
