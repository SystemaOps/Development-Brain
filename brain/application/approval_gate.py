"""Approval gate service (Phase 17).

Integrates human approval into workflows: given a policy evaluation, the gate
decides whether a workflow should pause; approval decisions (approve/reject)
unblock or halt it (Tasks 17.4, 17.6).
"""

from __future__ import annotations

from brain.domain.identity import ActorId
from brain.domain.policies import Approval, ApprovalDecision, ApprovalType
from brain.domain.workflow import ApprovalState, WorkflowState
from brain.ports.policies import ApprovalRepository


class ApprovalGate:
    """Pauses and resumes workflows based on human approvals."""

    def __init__(self, *, approvals: ApprovalRepository) -> None:
        self._approvals = approvals

    async def requires_approval(self, state: WorkflowState) -> ApprovalType | None:
        """Return the first open approval type required for this workflow."""
        for approval in await self._approvals.list_for_workflow(state.workflow_id):
            if approval.is_open:
                return approval.approval_type
        return None

    async def request_approval(
        self,
        *,
        state: WorkflowState,
        approval_type: ApprovalType,
        requested_by: ActorId | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Approval:
        approval = Approval(
            approval_type=approval_type,
            workflow_id=state.workflow_id,
            work_item_id=state.work_item_id,
            execution_id=state.current_execution_id,
            requested_by=requested_by,
            metadata=metadata or {},
        )
        await self._approvals.save_approval(approval)
        state.approval_state = ApprovalState.PENDING
        return approval

    async def decide(
        self,
        approval: Approval,
        *,
        decided_by: ActorId,
        decision: ApprovalDecision,
        reason: str = "",
    ) -> Approval:
        approval.decided_by = decided_by
        approval.decision = decision
        approval.reason = reason
        approval.decided_at = approval.decided_at
        await self._approvals.save_approval(approval)
        return approval

    async def apply_to_workflow(self, approval: Approval, state: WorkflowState) -> WorkflowState:
        """Apply an approval decision to a workflow state."""
        if approval.workflow_id != state.workflow_id:
            return state
        if approval.decision == ApprovalDecision.APPROVED:
            state.approval_state = ApprovalState.APPROVED
        elif approval.decision == ApprovalDecision.REJECTED:
            state.approval_state = ApprovalState.REJECTED
        elif approval.decision == ApprovalDecision.NEEDS_CHANGES:
            state.approval_state = ApprovalState.PENDING
        return state


__all__ = ["ApprovalGate"]
