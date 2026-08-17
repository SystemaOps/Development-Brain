"""In-memory approval repository reference implementation."""

from __future__ import annotations

import uuid

from brain.domain.identity import WorkflowId, WorkItemId
from brain.domain.policies import Approval


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
