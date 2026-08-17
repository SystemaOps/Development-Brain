"""Ports: the interfaces the brain core depends on.

Ports define contracts; adapters implement them.  Importing this package
never pulls in a provider SDK, database, workflow engine, or coding agent.
"""

from brain.ports.artifact_store import ArtifactStore
from brain.ports.checkpoint_store import CheckpointStore
from brain.ports.ci_validation import CIValidationPort
from brain.ports.code_intelligence import (
    CodeGraphRepository,
    CodeIntelligencePort,
    LanguageParser,
)
from brain.ports.context import ContextCapsuleRepository
from brain.ports.documentation import DocumentationPort
from brain.ports.embeddings import EmbeddingService
from brain.ports.event_bus import EventBus, EventHandler
from brain.ports.event_log import EventLogRepository
from brain.ports.executor import ExecutorPort
from brain.ports.executor_registry import ExecutorRegistry
from brain.ports.idempotency import IdempotencyStore
from brain.ports.knowledge_graph import GraphEntity, GraphRelation, KnowledgeGraphRepository
from brain.ports.observability import LogSink, MetricsRepository
from brain.ports.parsing import (
    DocumentParser,
    EntityExtractor,
    ParserRegistry,
    ParserSelectionPolicy,
)
from brain.ports.planning import PlanRepository
from brain.ports.policies import ApprovalRepository, PolicyProvider
from brain.ports.pull_request import PullRequest, PullRequestPort
from brain.ports.repositories import (
    ActorRepository,
    ArtifactRepository,
    DecisionRepository,
    DocumentRepository,
    EvidenceRepository,
    ExecutionRepository,
    ProjectRepository,
    RepositoryRepository,
    RequirementRepository,
    VerificationResultRepository,
    WorkItemRepository,
)
from brain.ports.repository_scan import (
    RepositoryChangeSetRepository,
    RepositorySnapshotRepository,
)
from brain.ports.runtime import RuntimeEvidenceRepository
from brain.ports.semantic_index import SemanticIndex
from brain.ports.software_catalog import SoftwareCatalogPort
from brain.ports.source_control import SourceControlPort
from brain.ports.topology import (
    DerivedSoftwareCatalog,
    SoftwareCatalogRepository,
    TopologyDiscoveryPort,
)
from brain.ports.verification import CommandRunner, VerificationRunRepository
from brain.ports.work_management import WorkManagementPort
from brain.ports.work_management_repo import WorkManagementIntegrationRepository
from brain.ports.workflow import WorkflowCheckpointRepository

__all__ = [
    "ActorRepository",
    "ApprovalRepository",
    "ArtifactRepository",
    "ArtifactStore",
    "CheckpointStore",
    "CIValidationPort",
    "CodeGraphRepository",
    "CodeIntelligencePort",
    "CommandRunner",
    "ContextCapsuleRepository",
    "DecisionRepository",
    "DerivedSoftwareCatalog",
    "DocumentParser",
    "DocumentRepository",
    "DocumentationPort",
    "EmbeddingService",
    "EntityExtractor",
    "EventBus",
    "EventHandler",
    "EventLogRepository",
    "EvidenceRepository",
    "ExecutionRepository",
    "ExecutorPort",
    "ExecutorRegistry",
    "GraphEntity",
    "GraphRelation",
    "IdempotencyStore",
    "KnowledgeGraphRepository",
    "LanguageParser",
    "LogSink",
    "MetricsRepository",
    "ParserRegistry",
    "ParserSelectionPolicy",
    "PlanRepository",
    "PolicyProvider",
    "ProjectRepository",
    "PullRequest",
    "PullRequestPort",
    "RepositoryChangeSetRepository",
    "RepositoryRepository",
    "RepositorySnapshotRepository",
    "RequirementRepository",
    "RuntimeEvidenceRepository",
    "SemanticIndex",
    "SoftwareCatalogPort",
    "SoftwareCatalogRepository",
    "SourceControlPort",
    "TopologyDiscoveryPort",
    "VerificationResultRepository",
    "VerificationRunRepository",
    "WorkItemRepository",
    "WorkManagementIntegrationRepository",
    "WorkManagementPort",
    "WorkflowCheckpointRepository",
]
