"""WorkItem domain.

Engineering work items keep four SEPARATE status tracks on purpose:

- ``human_work_status``        -- what the human-facing tool says
- ``implementation_status``    -- what the code actually shows
- ``verification_status``      -- what independent verification found
- ``pull_request_status``      -- PR lifecycle

Collapsing these into one status would hide valuable inconsistencies such as
"the ticket says DONE but verification FAILED".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.common import Priority
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    ActorId,
    ProjectId,
    RequirementId,
    WorkItemId,
    new_work_item_id,
)


class WorkItemType(StrEnum):
    EPIC = "epic"
    FEATURE = "feature"
    STORY = "story"
    TASK = "task"
    BUG = "bug"
    INVESTIGATION = "investigation"
    REFACTORING = "refactoring"
    VERIFICATION = "verification"
    DOCUMENTATION = "documentation"
    OPERATIONS = "operations"


class HumanWorkStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class ImplementationStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    CODE_MODIFIED = "code_modified"
    IMPLEMENTED = "implemented"
    IMPLEMENTED_UNVERIFIED = "implemented_unverified"


class VerificationStatus(StrEnum):
    NOT_VERIFIED = "not_verified"
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"


class PullRequestStatus(StrEnum):
    NOT_CREATED = "not_created"
    CREATED = "created"
    APPROVED = "approved"
    MERGED = "merged"
    REJECTED = "rejected"


class AcceptanceCriterion(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    description: str
    satisfied: bool = False


class Assignment(BaseModel):
    actor_id: ActorId
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    assigned_by: ActorId | None = None
    role: str | None = None


class WorkItem(BaseModel):
    id: WorkItemId = Field(default_factory=new_work_item_id)
    project_id: ProjectId
    type: WorkItemType = WorkItemType.TASK
    title: str
    description: str = ""
    priority: Priority | None = None
    parent_id: WorkItemId | None = None
    assignee: ActorId | None = None
    assignment: Assignment | None = None
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    requirement_refs: list[RequirementId] = Field(default_factory=list)
    external_refs: list[ExternalReference] = Field(default_factory=list)

    human_work_status: HumanWorkStatus = HumanWorkStatus.NEW
    implementation_status: ImplementationStatus = ImplementationStatus.NOT_STARTED
    verification_status: VerificationStatus = VerificationStatus.NOT_VERIFIED
    pull_request_status: PullRequestStatus = PullRequestStatus.NOT_CREATED
