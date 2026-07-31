from __future__ import annotations

from typing import Any, Protocol


class VectorStorePort(Protocol):
    async def ensure_schema(self) -> None:
        ...

    async def upsert_text(
        self,
        *,
        collection: str,
        object_id: str,
        text: str,
        properties: dict[str, Any],
        vector: list[float] | None = None,
    ) -> None:
        ...

    async def search(
        self,
        *,
        collection: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        ...
