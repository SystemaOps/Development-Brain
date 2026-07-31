from __future__ import annotations

from agent_core.config import settings


def get_checkpoint_database_url() -> str:
    if settings.checkpoint_database_url:
        return settings.checkpoint_database_url

    if settings.database_url.startswith("postgresql+asyncpg://"):
        return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    return settings.database_url