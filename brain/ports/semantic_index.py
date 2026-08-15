"""Semantic index port.

The semantic index is an INDEX, never the source of truth.  Implementations
(Weaviate, pgvector, Qdrant, ...) must satisfy the same contract tests.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from brain.domain.knowledge import SemanticRecord


@runtime_checkable
class SemanticIndex(Protocol):
    async def index(self, records: list[SemanticRecord]) -> None: ...

    async def delete(self, ids: list[uuid.UUID]) -> None: ...

    async def search(
        self, query: str, filters: dict[str, object], limit: int
    ) -> list[SemanticRecord]: ...
