from __future__ import annotations

from typing import Any, Protocol


class GraphStorePort(Protocol):
    async def ensure_schema(self) -> None:
        ...

    async def upsert_node(self, *, labels: tuple[str, ...], key: str, properties: dict[str, Any]) -> None:
        ...

    async def upsert_relation(
        self,
        *,
        from_key: str,
        to_key: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        ...
