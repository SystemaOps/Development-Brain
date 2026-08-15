"""Run infrastructure contract suites against in-memory reference adapters."""

from __future__ import annotations

import pytest

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.event_log import InMemoryEventLogRepository
from brain.adapters.in_memory.idempotency import InMemoryIdempotencyStore
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryRepositoryChangeSetRepository,
    InMemoryRepositorySnapshotRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.ports.event_bus import EventBus
from brain.ports.event_log import EventLogRepository
from brain.ports.idempotency import IdempotencyStore
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from brain.ports.repository_scan import (
    RepositoryChangeSetRepository,
    RepositorySnapshotRepository,
)
from brain.ports.semantic_index import SemanticIndex
from tests.contracts.event_bus import EventBusContract
from tests.contracts.event_log import EventLogRepositoryContract
from tests.contracts.idempotency import IdempotencyStoreContract
from tests.contracts.knowledge_graph import KnowledgeGraphRepositoryContract
from tests.contracts.repository_scan import (
    RepositoryChangeSetRepositoryContract,
    RepositorySnapshotRepositoryContract,
)
from tests.contracts.semantic_index import SemanticIndexContract


class TestInMemoryEventBus(EventBusContract):
    @pytest.fixture
    def event_bus(self) -> EventBus:
        return InMemoryEventBus()


class TestInMemoryIdempotencyStore(IdempotencyStoreContract):
    @pytest.fixture
    def idempotency(self) -> IdempotencyStore:
        return InMemoryIdempotencyStore()


class TestInMemoryEventLogRepository(EventLogRepositoryContract):
    @pytest.fixture
    def event_log(self) -> EventLogRepository:
        return InMemoryEventLogRepository()


class TestInMemoryKnowledgeGraph(KnowledgeGraphRepositoryContract):
    @pytest.fixture
    def knowledge_graph(self) -> KnowledgeGraphRepository:
        return InMemoryKnowledgeGraph()


class TestInMemorySemanticIndex(SemanticIndexContract):
    @pytest.fixture
    def semantic_index(self) -> SemanticIndex:
        return InMemorySemanticIndex()


class TestInMemoryRepositorySnapshotRepository(RepositorySnapshotRepositoryContract):
    @pytest.fixture
    def snapshots(self) -> RepositorySnapshotRepository:
        return InMemoryRepositorySnapshotRepository()


class TestInMemoryRepositoryChangeSetRepository(RepositoryChangeSetRepositoryContract):
    @pytest.fixture
    def change_sets(self) -> RepositoryChangeSetRepository:
        return InMemoryRepositoryChangeSetRepository()
