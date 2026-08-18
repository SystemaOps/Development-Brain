"""Runtime composition root (Phase 21).

``BrainContainer`` groups the already-implemented repositories, ports, and
application services; :func:`create_brain_container` is the one async factory
every runtime process uses.  Construction performs no I/O and no side effects
(migrations, ingestion, workflows); :meth:`BrainContainer.close` is the
idempotent shutdown path.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from brain.adapters.postgresql.database import PostgresRepositories, create_repositories
from brain.adapters.postgresql.unit_of_work import PostgresUnitOfWork
from brain.application.context_engine import ContextEngineService
from brain.application.planning import PlanningService
from brain.application.verification_engine import VerificationEngine
from brain.application.workflow_engine import WorkflowEngine
from brain.bootstrap.providers import (
    build_documentation,
    build_executor_registry,
    build_graph,
    build_postgres,
    build_pull_request,
    build_semantic_index,
    build_services,
    build_software_catalog,
    build_source_control,
    build_work_management,
)
from brain.bootstrap.settings import BrainSettings
from brain.domain.executor import ExecutorDescriptor
from brain.ports.documentation import DocumentationPort
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from brain.ports.pull_request import PullRequestPort
from brain.ports.semantic_index import SemanticIndex
from brain.ports.source_control import SourceControlPort
from brain.ports.work_management import WorkManagementPort

logger = logging.getLogger(__name__)


class BrainContainer:
    """One composition root wiring the Brain library into a runtime."""

    def __init__(
        self,
        *,
        settings: BrainSettings,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        repositories: PostgresRepositories,
        graph: KnowledgeGraphRepository,
        semantic_index: SemanticIndex,
        event_bus: Any,
        artifact_store: Any,
        executor_registry: Any,
        executor_descriptors: list[ExecutorDescriptor],
        work_management: WorkManagementPort | None,
        work_management_status: str,
        documentation_ports: list[DocumentationPort],
        software_catalog: Any,
        software_catalog_status: str,
        source_control: SourceControlPort | None,
        document_conversion: Any | None,
        pull_requests: PullRequestPort | None,
        capabilities: dict[str, str],
        services: dict[str, object],
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.session_factory = session_factory
        self.repositories = repositories
        self.graph = graph
        self.semantic_index = semantic_index
        self.event_bus = event_bus
        self.artifact_store = artifact_store
        self.executor_registry = executor_registry
        self.executor_descriptors = executor_descriptors
        self.work_management = work_management
        self.work_management_status = work_management_status
        self.documentation_ports = documentation_ports
        self.software_catalog = software_catalog
        self.software_catalog_status = software_catalog_status
        self.source_control = source_control
        self.document_conversion = document_conversion
        self.pull_requests = pull_requests
        self._capabilities = capabilities
        self._services = services
        self._closed = False

    # --- application services (convenience accessors) ---------------------

    @property
    def context_engine(self) -> ContextEngineService:
        return self._services["context_engine"]  # type: ignore[return-value]

    @property
    def planning(self) -> PlanningService:
        return self._services["planning"]  # type: ignore[return-value]

    @property
    def verification(self) -> VerificationEngine:
        return self._services["verification"]  # type: ignore[return-value]

    @property
    def workflow(self) -> WorkflowEngine:
        return self._services["workflow"]  # type: ignore[return-value]

    @property
    def services(self) -> dict[str, object]:
        return self._services

    # --- lifecycle --------------------------------------------------------

    def capabilities(self) -> dict[str, str]:
        """Snapshot of runtime capability statuses (Task 21.7/21.8)."""
        return dict(self._capabilities)

    def unit_of_work(self) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(self.session_factory)

    async def close(self) -> None:
        """Idempotent shutdown of all runtime-owned clients."""
        if self._closed:
            return
        self._closed = True

        closeables = [
            self.graph,
            self.semantic_index,
            self.artifact_store,
        ]
        for client in closeables:
            closer = getattr(client, "close", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:  # noqa: BLE001
                    logger.warning("error closing %s", type(client).__name__, exc_info=True)

        await self.engine.dispose()


async def create_brain_container(
    settings: BrainSettings | None = None,
) -> BrainContainer:
    """Construct the complete Brain runtime from one settings object.

    No migrations, ingestion, or workflows run as construction side effects.
    """
    settings = settings or BrainSettings()

    # 1. Infrastructure clients.
    engine, session_factory = build_postgres(settings)
    session = session_factory()
    repositories = create_repositories(session)

    # 2. Knowledge graph + semantic index (lazy adapters or in-memory fallback).
    graph = build_graph(settings)
    semantic_index = build_semantic_index(settings)

    # 3. Optional integrations.
    work_management, work_management_status = build_work_management(settings)
    documentation_ports = build_documentation(settings)
    software_catalog, software_catalog_status = build_software_catalog(
        settings, repositories.software_catalog
    )
    source_control = build_source_control(settings)
    document_conversion = None
    pull_requests = build_pull_request(settings)

    # 4. Executor registry with the Milestone-1 default executor.
    executor_registry = await build_executor_registry(settings)
    descriptors = await executor_registry.list()

    # 5. Application services.
    services = build_services(
        settings,
        repositories,
        graph=graph,
        semantic=semantic_index,
        executor_registry=executor_registry,
    )

    capabilities = {
        "postgres": "AVAILABLE",
        "neo4j": "AVAILABLE" if settings.storage_graph.uri else "DISABLED",
        "weaviate": "AVAILABLE" if settings.storage_semantic.host else "DISABLED",
        "redis": "AVAILABLE" if settings.storage_queue.url else "DISABLED",
        "work_management": work_management_status,
        "software_catalog": software_catalog_status,
        "documentation_git": "AVAILABLE" if settings.documentation.git_enabled else "DISABLED",
        "documentation_xwiki": "AVAILABLE" if settings.documentation.xwiki_enabled else "DISABLED",
        "document_conversion": "AVAILABLE" if settings.document_conversion.enabled else "DISABLED",
        "source_control": "AVAILABLE" if source_control is not None else "DISABLED",
        "coding_executor": "AVAILABLE"
        if settings.executors.coding_provider in {"fake", ""}
        else "DISABLED",
    }

    return BrainContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        repositories=repositories,
        graph=graph,
        semantic_index=semantic_index,
        event_bus=services["events"],
        artifact_store=services["artifacts"],
        executor_registry=executor_registry,
        executor_descriptors=descriptors,
        work_management=work_management,
        work_management_status=work_management_status,
        documentation_ports=documentation_ports,
        software_catalog=software_catalog,
        software_catalog_status=software_catalog_status,
        source_control=source_control,
        document_conversion=document_conversion,
        pull_requests=pull_requests,
        capabilities=capabilities,
        services=services,
    )


__all__ = ["BrainContainer", "create_brain_container"]
