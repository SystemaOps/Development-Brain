"""Run the Phase 3 infrastructure contracts against PostgreSQL."""

from __future__ import annotations

import pytest

from brain.adapters.postgresql.repositories import (
    PostgresEventLogRepository,
    PostgresIdempotencyStore,
    PostgresRepositoryChangeSetRepository,
    PostgresRepositorySnapshotRepository,
)
from brain.ports.event_log import EventLogRepository
from brain.ports.idempotency import IdempotencyStore
from brain.ports.repository_scan import (
    RepositoryChangeSetRepository,
    RepositorySnapshotRepository,
)
from tests.contracts.event_log import EventLogRepositoryContract
from tests.contracts.idempotency import IdempotencyStoreContract
from tests.contracts.repository_scan import (
    RepositoryChangeSetRepositoryContract,
    RepositorySnapshotRepositoryContract,
)


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
