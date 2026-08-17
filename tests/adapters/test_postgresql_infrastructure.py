"""Run the Phase 3 infrastructure contracts against PostgreSQL."""

from __future__ import annotations

import pytest

from brain.adapters.postgresql.repositories import (
    PostgresApprovalRepository,
    PostgresContextCapsuleRepository,
    PostgresEventLogRepository,
    PostgresIdempotencyStore,
    PostgresMetricsRepository,
    PostgresRepositoryChangeSetRepository,
    PostgresRepositorySnapshotRepository,
    PostgresRuntimeEvidenceRepository,
    PostgresVerificationRunRepository,
    PostgresWorkflowCheckpointRepository,
    PostgresWorkManagementIntegrationRepository,
)
from brain.ports.context import ContextCapsuleRepository
from brain.ports.event_log import EventLogRepository
from brain.ports.idempotency import IdempotencyStore
from brain.ports.observability import MetricsRepository
from brain.ports.policies import ApprovalRepository
from brain.ports.repository_scan import (
    RepositoryChangeSetRepository,
    RepositorySnapshotRepository,
)
from brain.ports.runtime import RuntimeEvidenceRepository
from brain.ports.verification import VerificationRunRepository
from brain.ports.work_management_repo import WorkManagementIntegrationRepository
from brain.ports.workflow import WorkflowCheckpointRepository
from tests.contracts.approval import ApprovalRepositoryContract
from tests.contracts.context_capsule import ContextCapsuleRepositoryContract
from tests.contracts.event_log import EventLogRepositoryContract
from tests.contracts.idempotency import IdempotencyStoreContract
from tests.contracts.metrics import MetricsRepositoryContract
from tests.contracts.repository_scan import (
    RepositoryChangeSetRepositoryContract,
    RepositorySnapshotRepositoryContract,
)
from tests.contracts.runtime import RuntimeEvidenceRepositoryContract
from tests.contracts.verification_run import VerificationRunRepositoryContract
from tests.contracts.work_management_integration import (
    WorkManagementIntegrationRepositoryContract,
)
from tests.contracts.workflow_checkpoint import WorkflowCheckpointRepositoryContract


class TestPostgresApprovalRepository(ApprovalRepositoryContract):
    @pytest.fixture
    def approvals(self, postgres_session) -> ApprovalRepository:
        return PostgresApprovalRepository(postgres_session)


class TestPostgresMetricsRepository(MetricsRepositoryContract):
    @pytest.fixture
    def metrics(self, postgres_session) -> MetricsRepository:
        return PostgresMetricsRepository(postgres_session)


class TestPostgresRuntimeEvidenceRepository(RuntimeEvidenceRepositoryContract):
    @pytest.fixture
    def runtime(self, postgres_session) -> RuntimeEvidenceRepository:
        return PostgresRuntimeEvidenceRepository(postgres_session)


class TestPostgresWorkflowCheckpointRepository(WorkflowCheckpointRepositoryContract):
    @pytest.fixture
    def workflow_checkpoints(self, postgres_session) -> WorkflowCheckpointRepository:
        return PostgresWorkflowCheckpointRepository(postgres_session)


class TestPostgresWorkManagementIntegrationRepository(WorkManagementIntegrationRepositoryContract):
    @pytest.fixture
    def work_management_integrations(self, postgres_session) -> WorkManagementIntegrationRepository:
        return PostgresWorkManagementIntegrationRepository(postgres_session)


class TestPostgresVerificationRunRepository(VerificationRunRepositoryContract):
    @pytest.fixture
    def verification_runs(self, postgres_session) -> VerificationRunRepository:
        return PostgresVerificationRunRepository(postgres_session)


class TestPostgresContextCapsuleRepository(ContextCapsuleRepositoryContract):
    @pytest.fixture
    def capsule_repository(self, postgres_session) -> ContextCapsuleRepository:
        return PostgresContextCapsuleRepository(postgres_session)


class TestPostgresIdempotencyStore(IdempotencyStoreContract):
    @pytest.fixture
    def idempotency(self, postgres_session) -> IdempotencyStore:
        return PostgresIdempotencyStore(postgres_session)


class TestPostgresEventLogRepository(EventLogRepositoryContract):
    @pytest.fixture
    def event_log(self, postgres_session) -> EventLogRepository:
        return PostgresEventLogRepository(postgres_session)


class TestPostgresRepositorySnapshotRepository(RepositorySnapshotRepositoryContract):
    @pytest.fixture
    def snapshots(self, postgres_session) -> RepositorySnapshotRepository:
        return PostgresRepositorySnapshotRepository(postgres_session)


class TestPostgresRepositoryChangeSetRepository(RepositoryChangeSetRepositoryContract):
    @pytest.fixture
    def change_sets(self, postgres_session) -> RepositoryChangeSetRepository:
        return PostgresRepositoryChangeSetRepository(postgres_session)
