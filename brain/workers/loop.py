"""Worker command loop (Phase 25).

Consumes commands from the queue and dispatches them, persisting failures
(attempt, category, message, correlation id, retry eligibility) so the worker
never silently loses work.  A single loop is sufficient for Milestone 1.
"""

from __future__ import annotations

import logging
import signal

from brain.application.command_dispatcher import CommandDispatcher
from brain.bootstrap.container import BrainContainer
from brain.domain.command_failure import (
    CommandFailure,
    CommandFailureCategory,
)
from brain.domain.commands import CommandEnvelope
from brain.ports.command_failure import CommandFailureRepository
from brain.ports.commands import CommandQueue

logger = logging.getLogger(__name__)


def classify_failure(exc: Exception) -> tuple[CommandFailureCategory, bool]:
    """Map an exception to a failure category and retry eligibility."""
    message = f"{type(exc).__name__}: {exc}"
    if "invalid" in message.lower() or "validation" in message.lower():
        return CommandFailureCategory.INVALID_INPUT, False
    if "verification" in message.lower():
        return CommandFailureCategory.VERIFICATION_FAILURE, True
    if "execution" in message.lower():
        return CommandFailureCategory.EXECUTION_FAILURE, True
    return CommandFailureCategory.INTERNAL, True


async def process_command(
    *,
    dispatcher: CommandDispatcher,
    failures: CommandFailureRepository,
    command: CommandEnvelope,
    attempt: int = 1,
) -> bool:
    """Handle one command; return True on success.

    On failure the exception is persisted as a :class:`CommandFailure` and
    re-raised so the caller can decide on requeue/dead-letter.
    """
    try:
        await dispatcher.dispatch(command)
        return True
    except Exception as exc:  # noqa: BLE001
        category, retry_eligible = classify_failure(exc)
        await failures.save(
            CommandFailure(
                command_id=command.command_id,
                command_type=command.command_type.value,
                attempt=attempt,
                category=category,
                message=f"{type(exc).__name__}: {exc}",
                correlation_id=command.correlation_id,
                retry_eligible=retry_eligible,
            )
        )
        logger.error(
            "command %s failed (attempt %d): %s",
            command.command_type.value,
            attempt,
            exc,
        )
        raise


class WorkerLoop:
    """Runs the command consumption loop with graceful shutdown."""

    def __init__(
        self,
        *,
        container: BrainContainer,
        dispatcher: CommandDispatcher,
        queue: CommandQueue,
        max_attempts: int = 3,
        poll_timeout_seconds: float = 1.0,
    ) -> None:
        self._container = container
        self._dispatcher = dispatcher
        self._queue = queue
        self._failures: CommandFailureRepository = container.repositories.command_failures
        self._max_attempts = max_attempts
        self._poll_timeout = poll_timeout_seconds
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run(self, *, max_commands: int | None = None) -> int:
        """Consume and process commands until stopped or the queue drains.

        Returns the number of commands processed.
        """
        processed = 0
        while not self._stop and (max_commands is None or processed < max_commands):
            command = await self._queue.consume(timeout_seconds=self._poll_timeout)
            if command is None:
                if max_commands is not None:
                    break
                continue

            success = False
            attempt = 1
            while attempt <= self._max_attempts and not success:
                try:
                    await process_command(
                        dispatcher=self._dispatcher,
                        failures=self._failures,
                        command=command,
                        attempt=attempt,
                    )
                    success = True
                except Exception:  # noqa: BLE001
                    if attempt >= self._max_attempts:
                        await self._queue.dead_letter(command, f"failed after {attempt} attempts")
                        break
                attempt += 1

            if success:
                await self._queue.acknowledge(command.command_id)
            processed += 1
        return processed


async def run_worker_once(
    container: BrainContainer,
    *,
    max_commands: int | None = None,
    poll_timeout_seconds: float = 0.2,
) -> int:
    """Convenience: run one drained pass over the queue (tests/CLI)."""
    dispatcher = container.services["command_dispatcher"]
    assert isinstance(dispatcher, CommandDispatcher)
    queue = container.services["command_queue"]
    assert isinstance(queue, CommandQueue)
    loop = WorkerLoop(
        container=container,
        dispatcher=dispatcher,
        queue=queue,
        poll_timeout_seconds=poll_timeout_seconds,
    )
    return await loop.run(max_commands=max_commands)


def install_signal_handlers(loop: WorkerLoop) -> None:
    """Bind SIGINT/SIGTERM to graceful worker shutdown."""

    def _handle(signum: int, frame: object) -> None:
        del signum, frame
        logger.info("shutdown signal received")
        loop.stop()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


__all__ = [
    "WorkerLoop",
    "classify_failure",
    "install_signal_handlers",
    "process_command",
    "run_worker_once",
]
