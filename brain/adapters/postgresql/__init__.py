"""PostgreSQL adapter: durable transactional state layer.

Implements the state repository ports from ``brain.ports.repositories`` on
top of SQLAlchemy 2.0 + asyncpg.  The adapter is the only place that knows
about SQLAlchemy models, connections, and transactions; application code only
sees the ports and the domain models.
"""

from brain.adapters.postgresql.config import DatabaseSettings
from brain.adapters.postgresql.database import (
    async_session_factory,
    create_async_engine,
    create_repositories,
)
from brain.adapters.postgresql.repositories import (
    PostgresActorRepository,
    PostgresArtifactRepository,
    PostgresDecisionRepository,
    PostgresDocumentRepository,
    PostgresEventLogRepository,
    PostgresEvidenceRepository,
    PostgresExecutionRepository,
    PostgresIdempotencyStore,
    PostgresProjectRepository,
    PostgresRepositoryChangeSetRepository,
    PostgresRepositoryRepository,
    PostgresRepositorySnapshotRepository,
    PostgresRequirementRepository,
    PostgresVerificationResultRepository,
    PostgresWorkItemRepository,
)
from brain.adapters.postgresql.tables import Base, metadata
from brain.adapters.postgresql.unit_of_work import PostgresUnitOfWork

__all__ = [
    "Base",
    "DatabaseSettings",
    "PostgresActorRepository",
    "PostgresArtifactRepository",
    "PostgresDecisionRepository",
    "PostgresDocumentRepository",
    "PostgresEventLogRepository",
    "PostgresEvidenceRepository",
    "PostgresExecutionRepository",
    "PostgresIdempotencyStore",
    "PostgresProjectRepository",
    "PostgresRepositoryRepository",
    "PostgresRepositoryChangeSetRepository",
    "PostgresRepositorySnapshotRepository",
    "PostgresRequirementRepository",
    "PostgresUnitOfWork",
    "PostgresVerificationResultRepository",
    "PostgresWorkItemRepository",
    "async_session_factory",
    "create_async_engine",
    "create_repositories",
    "metadata",
]
