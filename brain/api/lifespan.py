"""FastAPI lifespan (Phase 23).

Startup resolves settings, creates the :class:`BrainContainer`, and stores it
on ``app.state``.  Shutdown closes the container (idempotent).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from brain.bootstrap.container import BrainContainer, create_brain_container
from brain.bootstrap.settings import BrainSettings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: BrainSettings = app.state.settings
    container: BrainContainer = await create_brain_container(settings)
    app.state.container = container
    try:
        yield
    finally:
        await container.close()
