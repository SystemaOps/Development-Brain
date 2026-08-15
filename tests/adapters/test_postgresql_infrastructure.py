"""Run the Phase 3 infrastructure contracts against PostgreSQL."""

from __future__ import annotations

import pytest

from brain.adapters.postgresql.repositories import (
    PostgresEventLogRepository,
    PostgresIdempotencyStore,
)
from brain.ports.event_log import EventLogRepository
from brain.ports.idempotency import IdempotencyStore
from tests.contracts.event_log import EventLogRepositoryContract
from tests.contracts.idempotency import IdempotencyStoreContract


class TestPostgresIdempotencyStore(IdempotencyStoreContract):
    @pytest.fixture
    def idempotency(self, postgres_session) -> IdempotencyStore:
        return PostgresIdempotencyStore(postgres_session)


class TestPostgresEventLogRepository(EventLogRepositoryContract):
    @pytest.fixture
    def event_log(self, postgres_session) -> EventLogRepository:
        return PostgresEventLogRepository(postgres_session)
