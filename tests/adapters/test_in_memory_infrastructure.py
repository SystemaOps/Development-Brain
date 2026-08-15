"""Run infrastructure contract suites against in-memory reference adapters."""

from __future__ import annotations

import pytest

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.ports.event_bus import EventBus
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from brain.ports.semantic_index import SemanticIndex
from tests.contracts.event_bus import EventBusContract
from tests.contracts.knowledge_graph import KnowledgeGraphRepositoryContract
from tests.contracts.semantic_index import SemanticIndexContract


class TestInMemoryEventBus(EventBusContract):
    @pytest.fixture
    def event_bus(self) -> EventBus:
        return InMemoryEventBus()


class TestInMemoryKnowledgeGraph(KnowledgeGraphRepositoryContract):
    @pytest.fixture
    def knowledge_graph(self) -> KnowledgeGraphRepository:
        return InMemoryKnowledgeGraph()


class TestInMemorySemanticIndex(SemanticIndexContract):
    @pytest.fixture
    def semantic_index(self) -> SemanticIndex:
        return InMemorySemanticIndex()
