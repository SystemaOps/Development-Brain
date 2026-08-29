"""In-memory policies reference implementations (Phase 17)."""

from __future__ import annotations

import uuid

from brain.domain.identity import WorkflowId, WorkItemId
from brain.domain.policies import (
    Approval,
    ApprovalType,
    PolicyAction,
    PolicyRule,
    PolicySet,
    RiskLevel,
)


class InMemoryApprovalRepository:
    """In-memory storage for human-approval requests."""

    def __init__(self) -> None:
        self._approvals: dict[uuid.UUID, Approval] = {}

    async def save_approval(self, approval: Approval) -> Approval:
        self._approvals[approval.id] = approval
        return approval

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None:
        return self._approvals.get(approval_id)

    async def list_open_for_work_item(self, work_item_id: WorkItemId) -> list[Approval]:
        return [
            approval
            for approval in self._approvals.values()
            if approval.work_item_id == work_item_id and approval.is_open
        ]

    async def list_for_workflow(self, workflow_id: WorkflowId) -> list[Approval]:
        return [
            approval for approval in self._approvals.values() if approval.workflow_id == workflow_id
        ]


class DefaultPolicyProvider:
    """Default permissive policy set for the runtime container.

    High-risk work requires an execution approval; everything else is allowed
    automatically.  Configured policy can replace this provider later.
    """

    def __init__(self, policy_set: PolicySet | None = None) -> None:
        self._policy_set = policy_set or PolicySet(
            name="default",
            rules=[
                PolicyRule(
                    name="high risk requires approval",
                    risk_levels=[RiskLevel.HIGH],
                    action=PolicyAction.REQUIRE_APPROVAL,
                    approval_type=ApprovalType.EXECUTION,
                )
            ],
        )

    async def get_policy_set(self) -> PolicySet:
        return self._policy_set
