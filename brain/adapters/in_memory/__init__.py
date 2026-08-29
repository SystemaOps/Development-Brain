"""In-memory reference adapters.

These are reference implementations used to establish contract behavior and to
run application services and tests without external infrastructure.
"""

from brain.adapters.in_memory.artifact_store import InMemoryArtifactStore
from brain.adapters.in_memory.catalog import NullSoftwareCatalog
from brain.adapters.in_memory.checkpoint_store import InMemoryCheckpointStore
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.command_failure import InMemoryCommandFailureRepository
from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.event_log import InMemoryEventLogRepository
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.human_activity import (
    InMemoryActivityProjectionRepository,
    NullHumanActivityPort,
)
from brain.adapters.in_memory.idempotency import InMemoryIdempotencyStore
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.observability import (
    InMemoryLogSink,
    InMemoryMetricsRepository,
)
from brain.adapters.in_memory.observations import InMemoryObservationRepository
from brain.adapters.in_memory.optimization import (
    InMemoryContextFeedbackRepository,
    InMemoryExecutorQualityRepository,
)
from brain.adapters.in_memory.planning import InMemoryPlanRepository
from brain.adapters.in_memory.policies import (
    DefaultPolicyProvider,
    InMemoryApprovalRepository,
)
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
from brain.adapters.in_memory.runtime import InMemoryRuntimeEvidenceRepository
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.adapters.in_memory.verification import InMemoryVerificationRunRepository
from brain.adapters.in_memory.work_management import (
    InMemoryWorkManagementIntegrationRepository,
)
from brain.adapters.in_memory.workflow import InMemoryWorkflowCheckpointRepository

__all__ = [
    "InMemoryActorRepository",
    "InMemoryApprovalRepository",
    "InMemoryArtifactRepository",
    "InMemoryArtifactStore",
    "InMemoryCheckpointStore",
    "InMemoryCodeGraphRepository",
    "InMemoryCommandFailureRepository",
    "InMemoryContextCapsuleRepository",
    "InMemoryContextFeedbackRepository",
    "InMemoryDecisionRepository",
    "DefaultPolicyProvider",
    "InMemoryDocumentRepository",
    "InMemoryEventBus",
    "InMemoryEventLogRepository",
    "InMemoryExecutorRegistry",
    "InMemoryEvidenceRepository",
    "InMemoryExecutionRepository",
    "InMemoryExecutorRegistry",
    "InMemoryExecutorQualityRepository",
    "InMemoryActivityProjectionRepository",
    "InMemoryIdempotencyStore",
    "InMemoryKnowledgeGraph",
    "InMemoryLogSink",
    "InMemoryMetricsRepository",
    "InMemoryObservationRepository",
    "InMemoryPlanRepository",
    "NullHumanActivityPort",
    "InMemoryProjectRepository",
    "InMemoryRepositoryChangeSetRepository",
    "InMemoryRepositoryRepository",
    "InMemoryRepositorySnapshotRepository",
    "InMemoryRequirementRepository",
    "InMemoryRuntimeEvidenceRepository",
    "InMemorySemanticIndex",
    "InMemoryVerificationResultRepository",
    "InMemoryVerificationRunRepository",
    "InMemoryWorkItemRepository",
    "InMemoryWorkManagementIntegrationRepository",
    "InMemoryWorkflowCheckpointRepository",
    "NullSoftwareCatalog",
]
