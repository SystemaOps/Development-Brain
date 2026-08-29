"""Policies and human-approval domain model (Phase 17).

Makes automation configurable and safe: a risk classifier tags tasks
(Task 17.5), policies derive executor permissions and approval requirements
(Tasks 17.1, 17.2), and an :class:`Approval` entity records the human
decision so workflows can pause and resume (Tasks 17.3, 17.4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.executions import ExecutionPermissions
from brain.domain.identity import (
    ActorId,
    ExecutionId,
    WorkflowId,
    WorkItemId,
)


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalType(StrEnum):
    PLAN = "plan"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    PR = "pr"
    EXECUTION = "execution"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class PolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyRule(BaseModel):
    """One declarative policy rule (Task 17.1)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    risk_levels: list[RiskLevel] = Field(default_factory=list)
    action: PolicyAction
    approval_type: ApprovalType | None = None
    permissions: ExecutionPermissions | None = None


class PolicySet(BaseModel):
    """A configured set of policy rules."""

    name: str
    rules: list[PolicyRule] = Field(default_factory=list)

    def rules_for_risk(self, risk: RiskLevel) -> list[PolicyRule]:
        return [rule for rule in self.rules if risk in rule.risk_levels]


class Approval(BaseModel):
    """A persisted human-approval request and decision (Task 17.3)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    approval_type: ApprovalType
    workflow_id: WorkflowId | None = None
    work_item_id: WorkItemId | None = None
    execution_id: ExecutionId | None = None
    requested_by: ActorId | None = None
    decided_by: ActorId | None = None
    decision: ApprovalDecision = ApprovalDecision.PENDING
    reason: str = ""
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.decision == ApprovalDecision.PENDING


__all__ = [
    "Approval",
    "ApprovalDecision",
    "ApprovalType",
    "PolicyAction",
    "PolicyRule",
    "PolicySet",
    "RiskLevel",
]
