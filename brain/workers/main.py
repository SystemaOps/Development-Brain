"""Worker entry point (Phase 25).

``python -m brain.workers.main`` runs the worker process: settings loading,
BrainContainer creation, queue connection, graceful shutdown, structured
logging.
"""

from __future__ import annotations

import asyncio
import logging

from brain.application.command_dispatcher import CommandDispatcher
from brain.bootstrap.container import BrainContainer, create_brain_container
from brain.bootstrap.settings import BrainSettings
from brain.ports.commands import CommandQueue
from brain.workers.loop import WorkerLoop, install_signal_handlers

logger = logging.getLogger("brain.workers")


async def _run(settings: BrainSettings) -> int:
    container: BrainContainer = await create_brain_container(settings)
    dispatcher = container.services["command_dispatcher"]
    assert isinstance(dispatcher, CommandDispatcher)
    queue = container.services["command_queue"]
    assert isinstance(queue, CommandQueue)

    loop = WorkerLoop(container=container, dispatcher=dispatcher, queue=queue)
    install_signal_handlers(loop)

    logger.info("worker started; waiting for commands")
    try:
        processed = await loop.run()
        logger.info("worker stopped; processed %d commands", processed)
        return processed
    finally:
        await container.close()


async def main_async() -> int:
    settings = BrainSettings()
    logging.basicConfig(level=logging.INFO)
    return await _run(settings)


def main() -> None:
    """Console entry point (registered as ``brain-worker`` in Phase 31)."""
    code = asyncio.run(main_async())
    raise SystemExit(code)


if __name__ == "__main__":
    main()
