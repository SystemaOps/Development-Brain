"""Provider construction helpers (Phase 21).

Low-level factories used exclusively by the composition root.  Adapters
receive resolved settings; nothing here reads environment variables at module
import time.  Provider construction is lazy where the adapters support it
(Neo4j driver, Weaviate client), so constructing the container never performs
I/O by itself.  Providers without a Milestone-1 transport are left unbuilt and
reported through the capability registry instead of failing construction.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from brain.adapters.catalog.derived import DerivedCatalogPortAdapter
from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.executors.fake import FakeExecutor
from brain.adapters.in_memory.artifact_store import InMemoryArtifactStore
from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.observability import InMemoryLogSink
from brain.adapters.in_memory.policies import DefaultPolicyProvider
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.adapters.neo4j.knowledge_graph import Neo4jKnowledgeGraph
from brain.adapters.parsers.entity import NoopEntityExtractor
from brain.adapters.parsers.references import ReferenceExtractor
from brain.adapters.parsers.registry import DefaultParserRegistry
from brain.adapters.postgresql.config import DatabaseSettings as PostgresAdapterSettings
from brain.adapters.postgresql.database import (
    PostgresRepositories,
)
from brain.adapters.postgresql.database import (
    async_session_factory as _async_session_factory,
)
from brain.adapters.postgresql.database import (
    create_async_engine as _create_async_engine,
)
from brain.adapters.topology.discovery import TopologyDiscoverer
from brain.adapters.verification.command_runner import DeterministicCommandRunner
from brain.adapters.weaviate.semantic_index import WeaviateSemanticIndex
from brain.application.code_intelligence import CodeIntelligenceService
from brain.application.command_dispatcher import CommandDispatcher
from brain.application.context_engine import ContextEngineService
from brain.application.document_ingestion import DocumentIngestionService
from brain.application.execution_request_builder import ExecutionRequestBuilder
from brain.application.graph_projection import GraphProjectionService
from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.jit_retrieval import JustInTimeRetrieval
from brain.application.observability import ObservabilityService
from brain.application.observations import ObservationService
from brain.application.optimization import (
    ContextRankingFeedbackService,
    ExecutorQualityTracker,
    ModelRouter,
)
from brain.application.planning import PlanningService
from brain.application.policy_service import PolicyService
from brain.application.semantic_indexing import SemanticIndexingService
from brain.application.topology import TopologyDiscoveryService
from brain.application.verification_engine import VerificationEngine
from brain.application.workflow_engine import WorkflowEngine
from brain.bootstrap.settings import BrainSettings
from brain.domain.executor import (
    ExecutorCapabilities,
    ExecutorDescriptor,
    ExecutorKind,
)
from brain.ports.documentation import DocumentationPort
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from brain.ports.pull_request import PullRequestPort
from brain.ports.semantic_index import SemanticIndex
from brain.ports.source_control import SourceControlPort
from brain.ports.topology import SoftwareCatalogRepository
from brain.ports.work_management import WorkManagementPort

logger = logging.getLogger(__name__)


def build_postgres(
    settings: BrainSettings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Build the PostgreSQL engine and session factory from resolved settings."""
    adapter_settings = PostgresAdapterSettings(
        url=settings.storage_state.url,
        echo=settings.storage_state.echo,
        pool_size=settings.storage_state.pool_size,
        max_overflow=settings.storage_state.max_overflow,
        pool_pre_ping=settings.storage_state.pool_pre_ping,
    )
    engine = _create_async_engine(adapter_settings)
    return engine, _async_session_factory(engine)


def build_graph(settings: BrainSettings) -> KnowledgeGraphRepository:
    """Build the knowledge-graph repository (Neo4j when configured)."""
    if not settings.storage_graph.uri:
        return InMemoryKnowledgeGraph()
    from brain.adapters.neo4j.config import Neo4jSettings as Neo4jAdapterSettings

    return Neo4jKnowledgeGraph(
        settings=Neo4jAdapterSettings(
            uri=settings.storage_graph.uri,
            user=settings.storage_graph.user,
            password=settings.storage_graph.password,
            database=settings.storage_graph.database,
        )
    )


def build_semantic_index(settings: BrainSettings) -> SemanticIndex:
    """Build the semantic index (Weaviate when configured)."""
    if not settings.storage_semantic.host:
        return InMemorySemanticIndex(embeddings=HashEmbeddingService())
    from brain.adapters.weaviate.config import WeaviateSettings as WeaviateAdapterSettings

    return WeaviateSemanticIndex(
        embeddings=HashEmbeddingService(),
        settings=WeaviateAdapterSettings(
            host=settings.storage_semantic.host,
            port=settings.storage_semantic.port,
            grpc_port=settings.storage_semantic.grpc_port,
            scheme=settings.storage_semantic.scheme,
            class_name=settings.storage_semantic.class_name,
        ),
    )


def probe_http(url: str, timeout: float = 2.0) -> bool:
    """Reachability probe used for optional providers (no provider SDK)."""
    if not url:
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def build_work_management(settings: BrainSettings) -> tuple[WorkManagementPort | None, str]:
    """Build a work-management adapter from settings.

    Returns ``(adapter, status)`` where status is one of
    ``AVAILABLE`` / ``UNAVAILABLE`` / ``DISABLED`` / ``MISCONFIGURED``.
    External providers require an HTTP transport, which lands in a later
    integration phase; a configured-but-unbuildable provider reports
    ``UNAVAILABLE`` without raising.
    """
    wm = settings.work_management
    if not wm.enabled:
        return None, "DISABLED"
    if wm.provider in {"", "internal"}:
        return None, "AVAILABLE"
    if not wm.base_url:
        return None, "MISCONFIGURED"
    if probe_http(wm.base_url):
        return None, "AVAILABLE"
    return None, "UNAVAILABLE"


def build_documentation(settings: BrainSettings) -> list[DocumentationPort]:
    """Build documentation ports from settings.

    Git-markdown documentation needs a source-control transport; until a
    runtime transport exists the port list stays empty and the capability is
    reported separately.
    """
    del settings
    return []


def build_software_catalog(
    settings: BrainSettings, catalog: SoftwareCatalogRepository
) -> tuple[object, str]:
    """Build the software-catalog port (derived default).

    ``catalog`` is the :class:`SoftwareCatalogRepository` (a Postgres
    repository bundle attribute); it is wrapped in the derived catalog port.
    """
    if settings.software_catalog.provider == "derived":
        from brain.adapters.topology.catalog import DerivedSoftwareCatalog

        return DerivedCatalogPortAdapter(
            derived=DerivedSoftwareCatalog(catalog=catalog)
        ), "AVAILABLE"
    return None, "DISABLED"


async def build_executor_registry(
    settings: BrainSettings,
) -> InMemoryExecutorRegistry:
    """Build the executor registry and register the Milestone-1 default."""
    registry = InMemoryExecutorRegistry()
    if settings.executors.coding_provider in {"fake", ""}:
        await registry.register(
            ExecutorDescriptor(
                name="fake",
                kind=ExecutorKind.FAKE,
                capabilities=ExecutorCapabilities(
                    coding=True,
                    tool_support=True,
                    context_window=32000,
                ),
            )
        )
    return registry


def build_pull_request(settings: BrainSettings) -> PullRequestPort | None:
    """Build a pull-request port (Milestone 1: fake only)."""
    if settings.automation.auto_create_pr:
        from brain.adapters.verification.fake_pr import FakePullRequestAdapter

        return FakePullRequestAdapter()
    return None


def build_source_control(settings: BrainSettings) -> SourceControlPort | None:
    """Build a source-control port (Milestone 1: none)."""
    del settings
    return None


def build_command_queue(settings: BrainSettings) -> object:
    """Build the command queue.

    ``BRAIN_REDIS_PROVIDER=redis`` uses the Redis adapter; the default
    in-memory queue serves tests and local development behind the same port.
    """
    if settings.storage_queue.provider == "redis":
        from redis.asyncio import from_url

        from brain.adapters.queue.redis import RedisCommandQueue

        return RedisCommandQueue(
            from_url(settings.storage_queue.url, decode_responses=False),
            queue_name=settings.storage_queue.queue_name,
        )
    from brain.adapters.in_memory.commands import InMemoryCommandQueue

    return InMemoryCommandQueue()


def build_services(
    settings: BrainSettings,
    repos: PostgresRepositories,
    *,
    graph: KnowledgeGraphRepository,
    semantic: SemanticIndex,
    executor_registry: InMemoryExecutorRegistry,
) -> dict[str, object]:
    """Construct application services bound to a repository bundle."""
    events = InMemoryEventBus()
    artifacts = InMemoryArtifactStore()
    embeddings = HashEmbeddingService()

    hybrid = HybridRetrievalService(
        index=semantic,
        embeddings=embeddings,
        graph=graph,
    )
    code_intelligence = CodeIntelligenceService(
        parser=PythonAstParser(),
        repository=repos.code_graph,
    )
    context_engine = ContextEngineService(
        work_items=repos.work_items,
        requirements=repos.requirements,
        executions=repos.executions,
        verification_results=repos.verification_results,
        code_graph=repos.code_graph,
        knowledge_graph=graph,
        retrieval=hybrid,
        capsules=repos.context_capsules,
    )
    planning = PlanningService(
        plans=repos.plans,
        requirements=repos.requirements,
        documents=repos.documents,
        work_items=repos.work_items,
        executions=repos.executions,
        code_graph=repos.code_graph,
    )
    verification = VerificationEngine(
        runner=DeterministicCommandRunner(),
        results=repos.verification_runs,
        code_graph=repos.code_graph,
        project_commands={},
    )
    executor = FakeExecutor()
    workflow = WorkflowEngine(
        checkpoints=repos.workflow_checkpoints,
        context_builder=context_engine,
        executor_registry=executor_registry,
        executor=executor,
        verification=verification,
    )
    jit = JustInTimeRetrieval(
        code_graph=repos.code_graph,
        requirements=repos.requirements,
        decisions=repos.decisions,
        retrieval=hybrid,
    )
    ingestion = DocumentIngestionService(
        documents=repos.documents,
        parser_registry=DefaultParserRegistry(),
        entity_extractor=NoopEntityExtractor(),
        reference_extractor=ReferenceExtractor(),
        decisions=repos.decisions,
        event_bus=events,
    )
    topology = TopologyDiscoveryService(
        discoverer=TopologyDiscoverer(),
        catalog=repos.software_catalog,
    )
    semantic_indexing = SemanticIndexingService(
        index=semantic,
        documents=repos.documents,
        requirements=repos.requirements,
        decisions=repos.decisions,
        code_graph=repos.code_graph,
    )
    projection = GraphProjectionService(
        graph=graph,
        projects=repos.projects,
        requirements=repos.requirements,
        work_items=repos.work_items,
        repositories=repos.repositories,
        catalog=repos.software_catalog,
        decisions=repos.decisions,
        code_graph=repos.code_graph,
    )
    observability = ObservabilityService(
        metrics=repos.metrics,
        logs=InMemoryLogSink(),
    )
    observations = ObservationService(
        observations=repos.observations,
        event_bus=events,
    )
    policy = PolicyService(
        policies=DefaultPolicyProvider(),
    )
    quality = ExecutorQualityTracker(quality=repos.executor_quality)
    model_router = ModelRouter(quality=repos.executor_quality)
    ranking_feedback = ContextRankingFeedbackService(feedback=repos.context_feedback)
    request_builder = ExecutionRequestBuilder()

    services: dict[str, object] = {
        "events": events,
        "artifacts": artifacts,
        "hybrid_retrieval": hybrid,
        "code_intelligence": code_intelligence,
        "context_engine": context_engine,
        "planning": planning,
        "verification": verification,
        "workflow": workflow,
        "executor": executor,
        "jit_retrieval": jit,
        "document_ingestion": ingestion,
        "topology_discovery": topology,
        "semantic_indexing": semantic_indexing,
        "graph_projection": projection,
        "observability": observability,
        "observations": observations,
        "policy": policy,
        "executor_quality": quality,
        "model_router": model_router,
        "ranking_feedback": ranking_feedback,
        "execution_request_builder": request_builder,
        "command_queue": build_command_queue(settings),
        "command_dispatcher": CommandDispatcher(),
    }
    return services


__all__ = [
    "build_command_queue",
    "build_documentation",
    "build_executor_registry",
    "build_graph",
    "build_postgres",
    "build_pull_request",
    "build_services",
    "build_semantic_index",
    "build_software_catalog",
    "build_source_control",
    "build_work_management",
    "probe_http",
]
