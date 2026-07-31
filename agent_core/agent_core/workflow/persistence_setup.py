from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LangGraphPersistenceSetupResult:
    database_uri: str
    checkpointer_setup: bool
    store_setup: bool


async def initialize_langgraph_persistence(
    database_uri: str,
    *,
    include_store: bool = True,
    saver_cls: Any | None = None,
    store_cls: Any | None = None,
) -> LangGraphPersistenceSetupResult:
    if not database_uri.strip():
        raise ValueError("database_uri is required")

    if saver_cls is None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver_cls = AsyncPostgresSaver

    async with saver_cls.from_conn_string(database_uri) as checkpointer:
        await checkpointer.setup()

    store_setup = False
    if include_store:
        if store_cls is None:
            from langgraph.store.postgres.aio import AsyncPostgresStore

            store_cls = AsyncPostgresStore

        async with store_cls.from_conn_string(database_uri) as store:
            await store.setup()
        store_setup = True

    return LangGraphPersistenceSetupResult(
        database_uri=database_uri,
        checkpointer_setup=True,
        store_setup=store_setup,
    )
