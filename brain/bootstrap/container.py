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
from brain.bootstrap.capabilities import CapabilityRegistry
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
from brain.domain.capabilities import (
    CapabilityName,
    CapabilityStatus,
)
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
        capabilities: CapabilityRegistry,
        services: dict[str, object],
        session: AsyncSession | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.session_factory = session_factory
        self.session = session
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
        """Snapshot of runtime capability statuses (name -> status)."""
        return {
            name: descriptor.health.status.value
            for name, descriptor in self._capabilities.snapshot().items()
        }

    def capability_registry(self) -> CapabilityRegistry:
        """The registry itself, for health checks and readiness evaluation."""
        return self._capabilities

    def is_ready(self) -> bool:
        """Readiness: all required capabilities must be usable."""
        return self._capabilities.is_ready()

    def ready_problems(self) -> list[str]:
        return self._capabilities.ready_problems()

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

        if self.session is not None:
            try:
                await self.session.close()
            except Exception:  # noqa: BLE001
                logger.warning("error closing database session", exc_info=True)

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
        source_control=source_control,
    )
    document_conversion = services.get("document_conversion")

    # 5b. Phase 40 hardening services: API keys, audit, metrics, rate limiter,
    # workspace locks.
    from brain.adapters.in_memory.api_keys import InMemoryApiKeyStore, seed_keys_from_env
    from brain.application.audit import AuditService
    from brain.application.metrics import MetricsService
    from brain.application.rate_limiter import RateLimiter
    from brain.application.workspace_locks import (
        InMemoryWorkspaceLockStore,
        WorkspaceLockManager,
    )

    api_key_store = InMemoryApiKeyStore()
    await seed_keys_from_env(api_key_store, settings.security.api_keys)
    audit_log = repositories.audit_log
    audit_service = AuditService(log=audit_log)
    metrics = MetricsService()
    rate_limiter = RateLimiter()
    workspace_locks = WorkspaceLockManager(store=InMemoryWorkspaceLockStore())
    services["api_key_store"] = api_key_store
    services["audit"] = audit_service
    services["audit_log"] = audit_log
    services["metrics"] = metrics
    services["rate_limiter"] = rate_limiter
    services["workspace_locks"] = workspace_locks

    capabilities = _build_capability_registry(
        settings,
        session_factory,
        graph,
        semantic_index,
        work_management_status,
        software_catalog_status,
        source_control is not None,
    )

    # 6. Install canonical command handlers on the container dispatcher.
    from brain.application.command_handlers import install_command_handlers

    container_instance = BrainContainer(
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
        session=session,
    )
    install_command_handlers(container=container_instance)

    # Backstage reconciliation service (Phase 36): declared vs discovered.
    from brain.adapters.catalog.backstage import BackstageCatalogAdapter
    from brain.application.backstage_reconciliation import (
        BackstageReconciliationService,
    )
    from brain.application.observations import ObservationService

    backstage_port = (
        software_catalog if isinstance(software_catalog, BackstageCatalogAdapter) else None
    )
    observations_service = container_instance.services["observations"]
    assert isinstance(observations_service, ObservationService)
    container_instance.services["backstage_reconciliation"] = BackstageReconciliationService(
        backstage=backstage_port,
        container=container_instance,
        observations=observations_service,
    )

    # Pull request runtime service (Phase 38).
    from brain.application.pull_request_service import PullRequestService

    container_instance.services["pull_request_service"] = PullRequestService(
        container=container_instance
    )
    return container_instance


def _build_capability_registry(
    settings: BrainSettings,
    session_factory: async_sessionmaker[AsyncSession],
    graph: KnowledgeGraphRepository,
    semantic_index: SemanticIndex,
    work_management_status: str,
    software_catalog_status: str,
    source_control_available: bool = False,
) -> CapabilityRegistry:
    """Construct the runtime capability registry with health probes."""
    from brain.bootstrap.health import (
        make_neo4j_probe,
        make_postgres_probe,
        make_weaviate_probe,
    )

    registry = CapabilityRegistry()

    registry.register_health(
        CapabilityName.POSTGRES,
        provider="postgres",
        required=True,
        status=CapabilityStatus.AVAILABLE,
        probe=make_postgres_probe(session_factory),
    )
    registry.register_health(
        CapabilityName.NEO4J,
        provider="neo4j",
        required=False,
        status=(
            CapabilityStatus.AVAILABLE if settings.storage_graph.uri else CapabilityStatus.DISABLED
        ),
        probe=make_neo4j_probe(graph),
    )
    registry.register_health(
        CapabilityName.WEAVIATE,
        provider="weaviate",
        required=False,
        status=(
            CapabilityStatus.AVAILABLE
            if settings.storage_semantic.host
            else CapabilityStatus.DISABLED
        ),
        probe=make_weaviate_probe(semantic_index),
    )
    registry.register_health(
        CapabilityName.REDIS,
        provider="redis",
        required=False,
        status=(
            CapabilityStatus.AVAILABLE if settings.storage_queue.url else CapabilityStatus.DISABLED
        ),
    )
    registry.register_health(
        CapabilityName.WORK_MANAGEMENT,
        provider=settings.work_management.provider,
        required=settings.work_management.required,
        status=CapabilityStatus(work_management_status),
    )
    registry.register_health(
        CapabilityName.DOCUMENTATION_GIT,
        provider="git",
        required=False,
        status=(
            CapabilityStatus.AVAILABLE
            if settings.documentation.git_enabled
            else CapabilityStatus.DISABLED
        ),
    )
    registry.register_health(
        CapabilityName.DOCUMENTATION_XWIKI,
        provider="xwiki",
        required=settings.documentation.xwiki_required,
        status=(
            CapabilityStatus.AVAILABLE
            if settings.documentation.xwiki_enabled
            else CapabilityStatus.DISABLED
        ),
    )
    registry.register_health(
        CapabilityName.DOCUMENT_CONVERSION,
        provider=settings.document_conversion.provider,
        required=settings.document_conversion.required,
        status=(
            CapabilityStatus.AVAILABLE
            if (settings.document_conversion.enabled and settings.document_conversion.base_url)
            else CapabilityStatus.DISABLED
        ),
    )
    registry.register_health(
        CapabilityName.SOFTWARE_CATALOG,
        provider=settings.software_catalog.provider,
        required=False,
        status=CapabilityStatus(software_catalog_status),
    )
    registry.register_health(
        CapabilityName.SOURCE_CONTROL,
        provider=settings.source_control.provider,
        required=False,
        status=(
            CapabilityStatus.AVAILABLE if source_control_available else CapabilityStatus.DISABLED
        ),
    )
    registry.register_health(
        CapabilityName.CODING_EXECUTOR,
        provider=settings.executors.coding_provider,
        required=False,
        status=(
            CapabilityStatus.AVAILABLE
            if settings.executors.coding_provider in {"fake", "", "pi"}
            else CapabilityStatus.DISABLED
        ),
        detail=("pi executor configured" if settings.executors.coding_provider == "pi" else ""),
    )
    return registry


__all__ = ["BrainContainer", "create_brain_container"]
