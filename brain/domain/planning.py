"""Planning domain model (Phase 11).

Turns requirements and current project state into evidence-based engineering
plans: ambiguity assessment, requirement extraction (with provenance), plan
decomposition (feature/story/task), existing-implementation analysis, plan
reconciliation, validation, and planning evidence linking tasks back to the
requirements they derive from.

The plan is a brain-owned artifact: it is never published to OpenProject/Jira
here; external publication is a separate phase.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    PlanId,
    ProjectId,
    RequirementId,
    WorkItemId,
    new_plan_id,
)


class RequirementClarity(StrEnum):
    CLEAR = "clear"
    AMBIGUOUS = "ambiguous"
    MISSING_INFO = "missing_info"


class ImplementationStatus(StrEnum):
    """Existing-implementation classification (Task 11.4)."""

    NOT_IMPLEMENTED = "not_implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    IMPLEMENTED = "implemented"
    IMPLEMENTED_BUT_UNVERIFIED = "implemented_but_unverified"
    INCORRECT = "incorrect"
    UNKNOWN = "unknown"


class PlanItemType(StrEnum):
    FEATURE = "feature"
    STORY = "story"
    TASK = "task"


class PlanStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"


class AmbiguityAssessment(BaseModel):
    """Per-requirement ambiguity analysis (Task 11.1)."""

    requirement_id: RequirementId
    clarity: RequirementClarity = RequirementClarity.CLEAR
    reasons: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risk: float = 0.0


class PlanItem(BaseModel):
    """One planned unit of work: feature / story / task (Task 11.3)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: ProjectId
    item_type: PlanItemType = PlanItemType.TASK
    title: str
    description: str = ""
    requirement_refs: list[RequirementId] = Field(default_factory=list)
    parent_id: uuid.UUID | None = None
    dependency_ids: list[uuid.UUID] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    implementation_status: ImplementationStatus = ImplementationStatus.UNKNOWN
    evidence: list[str] = Field(default_factory=list)
    sort_order: int = 0


class PlanEvidence(BaseModel):
    """Record what caused a task to be created (Task 11.7)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    plan_id: PlanId
    source_requirement_id: RequirementId | None = None
    source_work_item_id: WorkItemId | None = None
    note: str = ""


class Plan(BaseModel):
    """The complete, reconciled engineering plan (Task 11.5/11.6)."""

    id: PlanId = Field(default_factory=new_plan_id)
    project_id: ProjectId
    title: str
    status: PlanStatus = PlanStatus.PROPOSED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    items: list[PlanItem] = Field(default_factory=list)
    assessments: list[AmbiguityAssessment] = Field(default_factory=list)
    evidence: list[PlanEvidence] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.validation_errors

    @property
    def tasks(self) -> list[PlanItem]:
        return [item for item in self.items if item.item_type == PlanItemType.TASK]


__all__ = [
    "AmbiguityAssessment",
    "ImplementationStatus",
    "Plan",
    "PlanEvidence",
    "PlanItem",
    "PlanItemType",
    "PlanStatus",
    "RequirementClarity",
]
