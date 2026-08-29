"""CLI container helper (Phase 30).

Every command opens one container through the composition root, runs its
application-service work, and closes it — the same root the API/worker/
scheduler use.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

import typer

from brain.bootstrap.container import BrainContainer, create_brain_container
from brain.bootstrap.settings import BrainSettings

T = TypeVar("T")


def async_command(fn: Callable[..., object]) -> Callable[..., object]:
    """Decorate an async handler so Typer can call it synchronously.

    ``functools.wraps`` preserves the original signature so Click can
    introspect parameters.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        coro = fn(*args, **kwargs)
        if inspect.iscoroutine(coro):
            return asyncio.run(coro)
        return coro

    return wrapper


@asynccontextmanager
async def cli_container(
    settings: BrainSettings | None = None,
) -> AsyncIterator[BrainContainer]:
    """Open one BrainContainer, commit pending writes, and close it."""
    container = await create_brain_container(settings or BrainSettings())
    try:
        yield container
    finally:
        session = container.session
        if session is not None and session.in_transaction():
            await session.commit()
        await container.close()


async def open_container(settings: BrainSettings | None = None) -> BrainContainer:
    return await create_brain_container(settings or BrainSettings())


def make_app() -> typer.Typer:
    """Build the typer application with all command groups registered."""
    from brain.cli.commands import build_cli

    return build_cli()
