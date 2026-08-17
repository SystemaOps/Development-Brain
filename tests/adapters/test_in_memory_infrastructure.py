"""Run infrastructure contract suites against in-memory reference adapters."""

from __future__ import annotations

import pytest

from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.event_log import InMemoryEventLogRepository
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.idempotency import InMemoryIdempotencyStore
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.observability import InMemoryMetricsRepository
from brain.adapters.in_memory.policies import InMemoryApprovalRepository
from brain.adapters.in_memory.repositories import (
    InMemoryRepositoryChangeSetRepository,
    InMemoryRepositorySnapshotRepository,
)
from brain.adapters.in_memory.runtime import InMemoryRuntimeEvidenceRepository
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.adapters.in_memory.verification import InMemoryVerificationRunRepository
from brain.adapters.in_memory.work_management import (
    InMemoryWorkManagementIntegrationRepository,
)
from brain.adapters.in_memory.workflow import InMemoryWorkflowCheckpointRepository
from brain.ports.context import ContextCapsuleRepository
from brain.ports.event_bus import EventBus
from brain.ports.event_log import EventLogRepository
from brain.ports.executor_registry import ExecutorRegistry
from brain.ports.idempotency import IdempotencyStore
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from brain.ports.observability import MetricsRepository
from brain.ports.policies import ApprovalRepository
from brain.ports.repository_scan import (
    RepositoryChangeSetRepository,
    RepositorySnapshotRepository,
)
from brain.ports.runtime import RuntimeEvidenceRepository
from brain.ports.semantic_index import SemanticIndex
from brain.ports.verification import VerificationRunRepository
from brain.ports.work_management_repo import WorkManagementIntegrationRepository
from brain.ports.workflow import WorkflowCheckpointRepository
from tests.contracts.approval import ApprovalRepositoryContract
from tests.contracts.context_capsule import ContextCapsuleRepositoryContract
from tests.contracts.event_bus import EventBusContract
from tests.contracts.event_log import EventLogRepositoryContract
from tests.contracts.executor_registry import ExecutorRegistryContract
from tests.contracts.idempotency import IdempotencyStoreContract
from tests.contracts.knowledge_graph import KnowledgeGraphRepositoryContract
from tests.contracts.metrics import MetricsRepositoryContract
from tests.contracts.repository_scan import (
    RepositoryChangeSetRepositoryContract,
    RepositorySnapshotRepositoryContract,
)
from tests.contracts.runtime import RuntimeEvidenceRepositoryContract
from tests.contracts.semantic_index import SemanticIndexContract
from tests.contracts.verification_run import VerificationRunRepositoryContract
from tests.contracts.work_management_integration import (
    WorkManagementIntegrationRepositoryContract,
)
from tests.contracts.workflow_checkpoint import WorkflowCheckpointRepositoryContract


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


class TestInMemoryExecutorRegistry(ExecutorRegistryContract):
    @pytest.fixture
    def executor_registry(self) -> ExecutorRegistry:
        return InMemoryExecutorRegistry()


class TestInMemorySemanticIndex(SemanticIndexContract):
    @pytest.fixture
    def semantic_index(self) -> SemanticIndex:
        return InMemorySemanticIndex(embeddings=HashEmbeddingService())


class TestInMemoryContextCapsuleRepository(ContextCapsuleRepositoryContract):
    @pytest.fixture
    def capsule_repository(self) -> ContextCapsuleRepository:
        return InMemoryContextCapsuleRepository()


class TestInMemoryVerificationRunRepository(VerificationRunRepositoryContract):
    @pytest.fixture
    def verification_runs(self) -> VerificationRunRepository:
        return InMemoryVerificationRunRepository()


class TestInMemoryWorkManagementIntegrationRepository(WorkManagementIntegrationRepositoryContract):
    @pytest.fixture
    def work_management_integrations(self) -> WorkManagementIntegrationRepository:
        return InMemoryWorkManagementIntegrationRepository()


class TestInMemoryWorkflowCheckpointRepository(WorkflowCheckpointRepositoryContract):
    @pytest.fixture
    def workflow_checkpoints(self) -> WorkflowCheckpointRepository:
        return InMemoryWorkflowCheckpointRepository()


class TestInMemoryApprovalRepository(ApprovalRepositoryContract):
    @pytest.fixture
    def approvals(self) -> ApprovalRepository:
        return InMemoryApprovalRepository()


class TestInMemoryMetricsRepository(MetricsRepositoryContract):
    @pytest.fixture
    def metrics(self) -> MetricsRepository:
        return InMemoryMetricsRepository()


class TestInMemoryRuntimeEvidenceRepository(RuntimeEvidenceRepositoryContract):
    @pytest.fixture
    def runtime(self) -> RuntimeEvidenceRepository:
        return InMemoryRuntimeEvidenceRepository()


class TestInMemoryRepositorySnapshotRepository(RepositorySnapshotRepositoryContract):
    @pytest.fixture
    def snapshots(self) -> RepositorySnapshotRepository:
        return InMemoryRepositorySnapshotRepository()


class TestInMemoryRepositoryChangeSetRepository(RepositoryChangeSetRepositoryContract):
    @pytest.fixture
    def change_sets(self) -> RepositoryChangeSetRepository:
        return InMemoryRepositoryChangeSetRepository()
