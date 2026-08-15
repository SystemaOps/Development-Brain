"""Alembic migration environment.

Uses the async SQLAlchemy engine so migrations run against the same
``postgresql+asyncpg`` URL used by the application.  The database URL is
resolved at runtime from ``BRAIN_DATABASE_URL`` (or ``-x sqlalchemy.url=...``),
falling back to the local-development default.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from brain.adapters.postgresql.config import DatabaseSettings
from brain.adapters.postgresql.tables import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _resolve_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return os.getenv("BRAIN_DATABASE_URL", DatabaseSettings().url)


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_async_engine(_resolve_url())

    async def _run() -> None:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
        await engine.dispose()

    asyncio.run(_run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()