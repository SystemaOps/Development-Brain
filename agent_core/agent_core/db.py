from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from agent_core.config import settings


class Base(DeclarativeBase):
    pass


# Ensure we're using an async-compatible database URL
# If using postgresql://, make sure asyncpg is available
try:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
except Exception as e:
    print(f"Database engine creation failed: {e}")
    raise

SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
