"""Policies and approvals ports (Phase 17).

``ApprovalRepository`` persists human-approval requests so workflows can pause
and resume; ``PolicyProvider`` supplies the configured policy set.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from brain.domain.identity import WorkflowId, WorkItemId
from brain.domain.policies import Approval, PolicySet


@runtime_checkable
class ApprovalRepository(Protocol):
    async def save_approval(self, approval: Approval) -> Approval: ...

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None: ...

    async def list_open_for_work_item(self, work_item_id: WorkItemId) -> list[Approval]: ...

    async def list_for_workflow(self, workflow_id: WorkflowId) -> list[Approval]: ...


@runtime_checkable
class PolicyProvider(Protocol):
    async def get_policy_set(self) -> PolicySet: ...


__all__ = ["ApprovalRepository", "PolicyProvider"]
