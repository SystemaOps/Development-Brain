"""Embedding service port (Task 9.3).

The brain must not hard-code one embedding model: local hash-based embeddings,
remote API embeddings, and future alternatives all implement this protocol.
The embedding is an INDEX-layer concern; canonical text always lives in the
source of truth (PostgreSQL).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingService(Protocol):
    """Produces dense vectors for text.

    Implementations must be deterministic for the same input so the semantic
    index stays consistent across re-indexes.
    """

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


__all__ = ["EmbeddingService"]
