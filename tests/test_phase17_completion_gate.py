"""Phase 17 golden tests and completion gate.

A configured high-risk task pauses for human approval while a low-risk task
continues automatically.  Approving unblocks the workflow; rejecting blocks it.
"""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.policies import InMemoryApprovalRepository
from brain.application.approval_gate import ApprovalGate
from brain.application.policy_service import PolicyService
from brain.domain.executions import ExecutionPermissions
from brain.domain.identity import ActorId, WorkflowId, WorkItemId
from brain.domain.policies import (
    ApprovalDecision,
    ApprovalType,
    PolicyAction,
    PolicyRule,
    PolicySet,
    RiskLevel,
)
from brain.domain.workflow import ApprovalState, WorkflowStage, WorkflowState
from brain.ports.policies import PolicyProvider


class _StaticPolicyProvider(PolicyProvider):
    def __init__(self, policy_set: PolicySet) -> None:
        self._policy_set = policy_set

    async def get_policy_set(self) -> PolicySet:
        return self._policy_set


def _make_policy_set() -> PolicySet:
    return PolicySet(
        name="default",
        rules=[
            PolicyRule(
                name="high risk requires execution approval",
                risk_levels=[RiskLevel.HIGH],
                action=PolicyAction.REQUIRE_APPROVAL,
                approval_type=ApprovalType.EXECUTION,
            ),
            PolicyRule(
                name="high risk cannot deploy",
                risk_levels=[RiskLevel.HIGH],
                action=PolicyAction.ALLOW,
                permissions=ExecutionPermissions(
                    repository_read=True,
                    repository_write=True,
                    git_commit=True,
                    create_pull_request=True,
                    deploy=False,
                ),
            ),
        ],
    )


async def _run_workflow(
    service: PolicyService,
    gate: ApprovalGate,
    *,
    title: str,
    decide: bool = False,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
) -> WorkflowState:
    state = WorkflowState(
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=WorkItemId(uuid.uuid4()),
        stage=WorkflowStage.EXECUTE,
    )
    evaluation = await service.evaluate(None, title=title)

    if not evaluation.allowed:
        state.approval_state = ApprovalState.REJECTED
        return state

    if evaluation.required_approvals:
        approval = await gate.request_approval(state=state, approval_type=ApprovalType.EXECUTION)
        assert state.approval_state == ApprovalState.PENDING
        if decide:
            approval.decision = decision
            approval.decided_by = ActorId(uuid.uuid4())
            approval.reason = "reviewed"
            await gate.apply_to_workflow(approval, state)
    return state


async def test_gate_high_risk_pauses_for_human_approval() -> None:
    approvals = InMemoryApprovalRepository()
    service = PolicyService(policies=_StaticPolicyProvider(_make_policy_set()))
    gate = ApprovalGate(approvals=approvals)

    state = await _run_workflow(service, gate, title="Apply production database migration")
    assert state.approval_state == ApprovalState.PENDING
    assert await gate.requires_approval(state) == ApprovalType.EXECUTION


async def test_gate_approval_unblocks_high_risk() -> None:
    approvals = InMemoryApprovalRepository()
    service = PolicyService(policies=_StaticPolicyProvider(_make_policy_set()))
    gate = ApprovalGate(approvals=approvals)

    state = await _run_workflow(
        service, gate, title="Apply production database migration", decide=True
    )
    assert state.approval_state == ApprovalState.APPROVED
    assert await gate.requires_approval(state) is None


async def test_gate_rejection_blocks_high_risk() -> None:
    approvals = InMemoryApprovalRepository()
    service = PolicyService(policies=_StaticPolicyProvider(_make_policy_set()))
    gate = ApprovalGate(approvals=approvals)

    state = await _run_workflow(
        service,
        gate,
        title="Apply production database migration",
        decide=True,
        decision=ApprovalDecision.REJECTED,
    )
    assert state.approval_state == ApprovalState.REJECTED
    assert await gate.requires_approval(state) is None


async def test_gate_low_risk_continues_automatically() -> None:
    approvals = InMemoryApprovalRepository()
    service = PolicyService(policies=_StaticPolicyProvider(_make_policy_set()))
    gate = ApprovalGate(approvals=approvals)

    state = await _run_workflow(service, gate, title="Refactor logging helper")
    assert state.approval_state == ApprovalState.NOT_REQUIRED
    assert await gate.requires_approval(state) is None
    assert approvals._approvals == {}
