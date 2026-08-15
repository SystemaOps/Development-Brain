"""Shared fixtures for PostgreSQL-backed tests.

Tests against PostgreSQL skip cleanly when no server is reachable, so the
suite still passes on machines without Docker/Postgres.  Start one with::

    docker compose up -d

Two databases are used:

- ``brain_test``            -- repository contract tests + completion gate
  (schema built with ``Base.metadata.create_all``, each test runs inside a
  transaction that is rolled back for isolation);
- ``brain_migration_test``  -- migration tests (schema built exclusively
  through Alembic upgrade/downgrade so the two concerns never collide).
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from brain.adapters.postgresql.config import DatabaseSettings
from brain.adapters.postgresql.database import async_session_factory, create_async_engine
from brain.adapters.postgresql.tables import Base

TEST_DATABASE_URL = os.getenv(
    "BRAIN_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/brain_test",
)

MIGRATION_TEST_DATABASE_URL = os.getenv(
    "BRAIN_MIGRATION_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/brain_migration_test",
)


def postgres_reachable(url: str) -> bool:
    """Return True if a PostgreSQL server answers on the URL's host/port.

    A plain TCP probe is used so this works both from sync code and from
    inside an async test/fixture (no ``asyncio.run`` of a driver call).
    """
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture
def postgres_settings() -> DatabaseSettings:
    return DatabaseSettings(url=TEST_DATABASE_URL, echo=False)


@pytest.fixture
async def postgres_engine(postgres_settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
    if not postgres_reachable(postgres_settings.url):
        pytest.skip("PostgreSQL is not available; start it with: docker compose up -d")
    engine = create_async_engine(postgres_settings)
    yield engine
    await engine.dispose()


@pytest.fixture
async def postgres_session(postgres_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session with the schema present, isolated per test via rollback."""
    async with postgres_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_session_factory(postgres_engine)
    session = factory()
    await session.begin()
    yield session
    await session.rollback()
    await session.close()
