"""Engine, session factory, and repository factory for PostgreSQL.

Nothing here leaks into application code: callers obtain repositories either
through :func:`create_repositories` (explicit session) or through
:class:`~brain.adapters.postgresql.unit_of_work.PostgresUnitOfWork`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as _create_async_engine,
)

from brain.adapters.postgresql.config import DatabaseSettings
from brain.adapters.postgresql.repositories import (
    PostgresActorRepository,
    PostgresArtifactRepository,
    PostgresCodeGraphRepository,
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
    PostgresSoftwareCatalogRepository,
    PostgresVerificationResultRepository,
    PostgresWorkItemRepository,
)

type SessionFactory = async_sessionmaker[AsyncSession]


def create_async_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build an async engine from :class:`DatabaseSettings`."""
    return _create_async_engine(
        settings.url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=settings.pool_pre_ping,
    )


def async_session_factory(engine: AsyncEngine) -> SessionFactory:
    """Build an async session factory bound to ``engine``."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class PostgresRepositories:
    """All state repositories bound to one :class:`AsyncSession`.

    Repositories in this bundle share the session, so multi-entity writes
    performed across them are atomic under a single transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.projects = PostgresProjectRepository(session)
        self.repositories = PostgresRepositoryRepository(session)
        self.actors = PostgresActorRepository(session)
        self.work_items = PostgresWorkItemRepository(session)
        self.requirements = PostgresRequirementRepository(session)
        self.documents = PostgresDocumentRepository(session)
        self.executions = PostgresExecutionRepository(session)
        self.decisions = PostgresDecisionRepository(session)
        self.evidence = PostgresEvidenceRepository(session)
        self.artifacts = PostgresArtifactRepository(session)
        self.verification_results = PostgresVerificationResultRepository(session)
        self.idempotency = PostgresIdempotencyStore(session)
        self.event_log = PostgresEventLogRepository(session)
        self.repository_snapshots = PostgresRepositorySnapshotRepository(session)
        self.repository_change_sets = PostgresRepositoryChangeSetRepository(session)
        self.software_catalog = PostgresSoftwareCatalogRepository(session)
        self.code_graph = PostgresCodeGraphRepository(session)

    @property
    def session(self) -> AsyncSession:
        return self._session


def create_repositories(session: AsyncSession) -> PostgresRepositories:
    """Create a session-bound repository bundle."""
    return PostgresRepositories(session)
