"""In-memory reference adapters.

These are reference implementations used to establish contract behavior and to
run application services and tests without external infrastructure.
"""

from brain.adapters.in_memory.artifact_store import InMemoryArtifactStore
from brain.adapters.in_memory.catalog import NullSoftwareCatalog
from brain.adapters.in_memory.checkpoint_store import InMemoryCheckpointStore
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.event_log import InMemoryEventLogRepository
from brain.adapters.in_memory.idempotency import InMemoryIdempotencyStore
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryActorRepository,
    InMemoryArtifactRepository,
    InMemoryDecisionRepository,
    InMemoryDocumentRepository,
    InMemoryEvidenceRepository,
    InMemoryExecutionRepository,
    InMemoryProjectRepository,
    InMemoryRepositoryChangeSetRepository,
    InMemoryRepositoryRepository,
    InMemoryRepositorySnapshotRepository,
    InMemoryRequirementRepository,
    InMemoryVerificationResultRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex

__all__ = [
    "InMemoryActorRepository",
    "InMemoryArtifactRepository",
    "InMemoryArtifactStore",
    "InMemoryCheckpointStore",
    "InMemoryCodeGraphRepository",
    "InMemoryContextCapsuleRepository",
    "InMemoryDecisionRepository",
    "InMemoryDocumentRepository",
    "InMemoryEventBus",
    "InMemoryEventLogRepository",
    "InMemoryEvidenceRepository",
    "InMemoryExecutionRepository",
    "InMemoryIdempotencyStore",
    "InMemoryKnowledgeGraph",
    "InMemoryProjectRepository",
    "InMemoryRepositoryChangeSetRepository",
    "InMemoryRepositoryRepository",
    "InMemoryRepositorySnapshotRepository",
    "InMemoryRequirementRepository",
    "InMemorySemanticIndex",
    "InMemoryVerificationResultRepository",
    "InMemoryWorkItemRepository",
    "NullSoftwareCatalog",
]
