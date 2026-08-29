"""Observation domain model (Phase 26).

The engineering journal: a canonical, evidence-backed representation of
meaningful Brain findings, independent of any human tool.  An Observation
carries type, severity, visibility, status, relationships to canonical
entities (project, requirement, work item, repository revision, capsule,
execution, verification, artifact, evidence, decision), and optional evidence
references (Task 26.2/26.3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ArtifactId,
    ContextCapsuleId,
    DecisionId,
    EvidenceId,
    ExecutionId,
    ObservationId,
    ProjectId,
    RepositoryId,
    RequirementId,
    VerificationId,
    WorkItemId,
    new_observation_id,
)


class ObservationType(StrEnum):
    DISCOVERY = "discovery"
    WARNING = "warning"
    CONFLICT = "conflict"
    IMPLEMENTATION_STATUS = "implementation_status"
    SCOPE_CHANGE = "scope_change"
    ASSUMPTION = "assumption"
    VERIFICATION_FAILURE = "verification_failure"
    VERIFICATION_PASS = "verification_pass"
    BLOCKER = "blocker"
    DEPENDENCY_DISCOVERED = "dependency_discovered"
    ARCHITECTURE_VIOLATION = "architecture_violation"
    HUMAN_ACTION_REQUIRED = "human_action_required"


class ObservationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ObservationVisibility(StrEnum):
    INTERNAL = "internal"
    TEAM = "team"
    IMPORTANT = "important"


class ObservationStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Observation(BaseModel):
    """One meaningful engineering finding (Task 26.2)."""

    id: ObservationId = Field(default_factory=new_observation_id)
    project_id: ProjectId
    work_item_id: WorkItemId | None = None
    execution_id: ExecutionId | None = None
    requirement_id: RequirementId | None = None
    repository_id: RepositoryId | None = None
    repository_revision: str | None = None
    context_capsule_id: ContextCapsuleId | None = None
    verification_id: VerificationId | None = None
    artifact_id: ArtifactId | None = None
    evidence_id: EvidenceId | None = None
    decision_id: DecisionId | None = None

    observation_type: ObservationType
    severity: ObservationSeverity = ObservationSeverity.INFO
    visibility: ObservationVisibility = ObservationVisibility.INTERNAL
    status: ObservationStatus = ObservationStatus.OPEN

    title: str
    body: str = ""

    source: str = "brain"
    evidence_refs: list[uuid.UUID] = Field(default_factory=list)
    requires_human_attention: bool = False

    dedup_key: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None


__all__ = [
    "Observation",
    "ObservationSeverity",
    "ObservationStatus",
    "ObservationType",
    "ObservationVisibility",
]
