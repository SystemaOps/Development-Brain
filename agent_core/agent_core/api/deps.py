from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from agent_core.db import SessionFactory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionFactory() as session:
        yield session
