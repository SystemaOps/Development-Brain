"""Ports: the interfaces the brain core depends on.

Ports define contracts; adapters implement them.  Importing this package
never pulls in a provider SDK, database, workflow engine, or coding agent.
"""

from brain.ports.artifact_store import ArtifactStore
from brain.ports.checkpoint_store import CheckpointStore
from brain.ports.ci_validation import CIValidationPort
from brain.ports.documentation import DocumentationPort
from brain.ports.event_bus import EventBus, EventHandler
from brain.ports.event_log import EventLogRepository
from brain.ports.executor import ExecutorPort
from brain.ports.idempotency import IdempotencyStore
from brain.ports.knowledge_graph import GraphEntity, GraphRelation, KnowledgeGraphRepository
from brain.ports.parsing import (
    DocumentParser,
    EntityExtractor,
    ParserRegistry,
    ParserSelectionPolicy,
)
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
from brain.ports.semantic_index import SemanticIndex
from brain.ports.software_catalog import SoftwareCatalogPort
from brain.ports.source_control import SourceControlPort
from brain.ports.work_management import WorkManagementPort

__all__ = [
    "ActorRepository",
    "ArtifactRepository",
    "ArtifactStore",
    "CheckpointStore",
    "CIValidationPort",
    "DecisionRepository",
    "DocumentParser",
    "DocumentRepository",
    "DocumentationPort",
    "EntityExtractor",
    "EventBus",
    "EventHandler",
    "EventLogRepository",
    "EvidenceRepository",
    "ExecutionRepository",
    "ExecutorPort",
    "GraphEntity",
    "GraphRelation",
    "IdempotencyStore",
    "KnowledgeGraphRepository",
    "ParserRegistry",
    "ParserSelectionPolicy",
    "ProjectRepository",
    "PullRequest",
    "PullRequestPort",
    "RepositoryChangeSetRepository",
    "RepositoryRepository",
    "RepositorySnapshotRepository",
    "RequirementRepository",
    "SemanticIndex",
    "SoftwareCatalogPort",
    "SourceControlPort",
    "VerificationResultRepository",
    "WorkItemRepository",
    "WorkManagementPort",
]
