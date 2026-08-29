"""Run the knowledge graph contract against Neo4j when reachable.

Skips cleanly when no Neo4j server is available (start with ``docker compose
up -d``).  Each test class uses a fresh adapter against a dedicated database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from brain.adapters.neo4j import Neo4jKnowledgeGraph, Neo4jSettings, neo4j_reachable
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from tests.contracts.knowledge_graph import KnowledgeGraphRepositoryContract

NEO4J_URI = "bolt://localhost:7687"
pytestmark = pytest.mark.skipif(
    not neo4j_reachable(NEO4J_URI),
    reason="Neo4j is not available; start it with: docker compose up -d",
)


@pytest.fixture
def neo4j_settings() -> Neo4jSettings:
    return Neo4jSettings(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        database="neo4j",
    )


class TestNeo4jKnowledgeGraph(KnowledgeGraphRepositoryContract):
    @pytest.fixture
    async def knowledge_graph(
        self, neo4j_settings: Neo4jSettings
    ) -> AsyncIterator[KnowledgeGraphRepository]:
        adapter = Neo4jKnowledgeGraph(neo4j_settings)
        await adapter.clear()
        yield adapter
        await adapter.close()
