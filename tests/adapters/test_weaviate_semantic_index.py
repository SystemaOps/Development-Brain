"""Run the semantic index contract against Weaviate when reachable.

Skips cleanly when no Weaviate server is available (start with ``docker compose
up -d``).  Uses a dedicated class per run; the in-memory reference adapter
defines the expected behavior.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.weaviate import WeaviateSemanticIndex, WeaviateSettings, weaviate_reachable
from brain.ports.semantic_index import SemanticIndex
from tests.contracts.semantic_index import SemanticIndexContract

_SETTINGS = WeaviateSettings(class_name="SemanticRecordTest")
pytestmark = pytest.mark.skipif(
    not weaviate_reachable(_SETTINGS),
    reason="Weaviate is not available; start it with: docker compose up -d",
)


class TestWeaviateSemanticIndex(SemanticIndexContract):
    @pytest.fixture
    async def semantic_index(self) -> AsyncIterator[SemanticIndex]:
        adapter = WeaviateSemanticIndex(embeddings=HashEmbeddingService(), settings=_SETTINGS)
        await adapter.clear()
        yield adapter
        await adapter.close()
