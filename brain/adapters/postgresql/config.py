"""PostgreSQL connection configuration.

Settings are read from environment variables with sensible local-development
defaults so the adapter works out of the box against the ``docker-compose``
service while remaining overridable for tests and containers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseSettings:
    """Immutable settings used to build an async PostgreSQL engine."""

    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Build settings from ``BRAIN_DATABASE_URL`` and friends."""
        return cls(
            url=os.getenv("BRAIN_DATABASE_URL", cls.url),
            echo=os.getenv("BRAIN_DATABASE_ECHO", "false").lower() in {"1", "true", "yes"},
            pool_size=int(os.getenv("BRAIN_DATABASE_POOL_SIZE", str(cls.pool_size))),
            max_overflow=int(os.getenv("BRAIN_DATABASE_MAX_OVERFLOW", str(cls.max_overflow))),
        )
