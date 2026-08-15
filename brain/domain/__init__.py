"""Canonical domain model of the Software Development Brain.

Importing this package must never pull in provider SDKs, databases, workflow
engines, or coding agents.  The domain depends only on Pydantic.
"""

from brain.domain.actors import Actor, ActorType
from brain.domain.artifacts import Artifact, ArtifactType
from brain.domain.common import Priority
from brain.domain.decisions import Decision, DecisionStatus
from brain.domain.documents import (
    Document,
    DocumentNode,
    DocumentNodeType,
    DocumentSource,
    DocumentType,
    DocumentVersion,
    SourceArtifact,
)
from brain.domain.events import EventEnvelope, EventType
from brain.domain.evidence import Evidence, EvidenceType
from brain.domain.executions import (
    Execution,
    ExecutionPermissions,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)
from brain.domain.external_reference import ExternalReference, SourceReference
from brain.domain.identity import (
    ActorId,
    ArtifactId,
    ContextCapsuleId,
    DecisionId,
    DocumentId,
    DocumentVersionId,
    EvidenceId,
    ExecutionId,
    ProjectId,
    RepositoryId,
    RequirementId,
    VerificationId,
    WorkflowId,
    WorkItemId,
)
from brain.domain.knowledge import (
    DiscoveryMethod,
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeOrigin,
    RevisionScope,
    SemanticRecord,
)
from brain.domain.projects import Project, ProjectStatus
from brain.domain.repositories import Repository
from brain.domain.requirements import (
    Constraint,
    ConstraintKind,
    Requirement,
    RequirementSource,
    RequirementSourceType,
    RequirementStatus,
)
from brain.domain.software_model import (
    ComponentType,
    Interface,
    InterfaceType,
    Resource,
    ResourceType,
    SoftwareComponent,
    SoftwareDomain,
    System,
)
from brain.domain.verification import VerificationResult, VerificationVerdict
from brain.domain.work_items import (
    AcceptanceCriterion,
    Assignment,
    HumanWorkStatus,
    ImplementationStatus,
    PullRequestStatus,
    VerificationStatus,
    WorkItem,
    WorkItemType,
)

__all__ = [
    "AcceptanceCriterion",
    "Actor",
    "ActorId",
    "ActorType",
    "Artifact",
    "ArtifactId",
    "ArtifactType",
    "Assignment",
    "ComponentType",
    "Constraint",
    "ConstraintKind",
    "ContextCapsuleId",
    "Decision",
    "DecisionId",
    "DecisionStatus",
    "DiscoveryMethod",
    "Document",
    "DocumentId",
    "DocumentNode",
    "DocumentNodeType",
    "DocumentSource",
    "DocumentType",
    "DocumentVersion",
    "DocumentVersionId",
    "EventEnvelope",
    "EventType",
    "Evidence",
    "EvidenceId",
    "EvidenceType",
    "Execution",
    "ExecutionId",
    "ExecutionPermissions",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "ExternalReference",
    "HumanWorkStatus",
    "ImplementationStatus",
    "Interface",
    "InterfaceType",
    "KnowledgeConfidence",
    "KnowledgeEvidence",
    "KnowledgeOrigin",
    "Priority",
    "Project",
    "ProjectId",
    "ProjectStatus",
    "PullRequestStatus",
    "Repository",
    "RepositoryId",
    "Requirement",
    "RequirementId",
    "RequirementSource",
    "RequirementSourceType",
    "RequirementStatus",
    "Resource",
    "ResourceType",
    "RevisionScope",
    "SemanticRecord",
    "SoftwareComponent",
    "SoftwareDomain",
    "SourceArtifact",
    "SourceReference",
    "System",
    "VerificationId",
    "VerificationResult",
    "VerificationStatus",
    "VerificationVerdict",
    "WorkItem",
    "WorkItemId",
    "WorkItemType",
    "WorkflowId",
]
