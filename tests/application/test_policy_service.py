"""Phase 17 application tests: risk classification, policy evaluation, approvals."""

from __future__ import annotations

import uuid

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


class StaticPolicyProvider(PolicyProvider):
    def __init__(self, policy_set: PolicySet) -> None:
        self._policy_set = policy_set

    async def get_policy_set(self) -> PolicySet:
        return self._policy_set


def _default_policy_set() -> PolicySet:
    return PolicySet(
        name="default",
        rules=[
            PolicyRule(
                name="high risk requires approval",
                risk_levels=[RiskLevel.HIGH],
                action=PolicyAction.REQUIRE_APPROVAL,
                approval_type=ApprovalType.EXECUTION,
            ),
            PolicyRule(
                name="high risk restricts deploy",
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


async def test_classify_low_risk() -> None:
    service = PolicyService(policies=StaticPolicyProvider(_default_policy_set()))
    result = await service.classify_risk(None, title="Refactor logging helper")
    assert result.risk == RiskLevel.LOW


async def test_classify_high_risk_database_migration() -> None:
    service = PolicyService(policies=StaticPolicyProvider(_default_policy_set()))
    result = await service.classify_risk(None, title="Add migration for users table")
    assert result.risk == RiskLevel.HIGH
    assert result.reasons


async def test_classify_high_risk_auth() -> None:
    service = PolicyService(policies=StaticPolicyProvider(_default_policy_set()))
    result = await service.classify_risk(None, title="Replace authentication token flow")
    assert result.risk == RiskLevel.HIGH


async def test_classify_medium_risk_api() -> None:
    service = PolicyService(policies=StaticPolicyProvider(_default_policy_set()))
    result = await service.classify_risk(None, title="Expose new REST endpoint")
    assert result.risk == RiskLevel.MEDIUM


async def test_evaluate_low_risk_allows_without_approval() -> None:
    service = PolicyService(policies=StaticPolicyProvider(_default_policy_set()))
    result = await service.evaluate(None, title="Refactor logging helper")
    assert result.allowed
    assert result.required_approvals == []
    assert result.permissions.repository_read


async def test_evaluate_high_risk_requires_approval_and_blocks_deploy() -> None:
    service = PolicyService(policies=StaticPolicyProvider(_default_policy_set()))
    result = await service.evaluate(None, title="Run database migration in production")
    assert result.allowed
    assert result.required_approvals == [ApprovalType.EXECUTION]
    assert not result.permissions.deploy


async def test_evaluate_deny_rule_blocks() -> None:
    policy_set = PolicySet(
        name="blocking",
        rules=[
            PolicyRule(
                name="no secrets access",
                risk_levels=[RiskLevel.HIGH],
                action=PolicyAction.DENY,
            )
        ],
    )
    service = PolicyService(policies=StaticPolicyProvider(policy_set))
    result = await service.evaluate(None, title="Read production secrets into log")
    assert not result.allowed


async def test_approval_decision_round_trip() -> None:
    service = PolicyService(policies=StaticPolicyProvider(_default_policy_set()))
    approval = await service.request_approval(
        approval_type=ApprovalType.EXECUTION,
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=WorkItemId(uuid.uuid4()),
    )
    assert approval.is_open

    decided = await service.decide_approval(
        approval,
        decided_by=ActorId(uuid.uuid4()),
        decision=ApprovalDecision.APPROVED,
        reason="looks good",
    )
    assert decided.decision == ApprovalDecision.APPROVED
    assert not decided.is_open
    assert decided.decided_at is not None


async def test_approval_gate_requests_and_applies() -> None:
    from brain.adapters.in_memory.policies import InMemoryApprovalRepository

    approvals = InMemoryApprovalRepository()
    gate = ApprovalGate(approvals=approvals)
    state = WorkflowState(
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=WorkItemId(uuid.uuid4()),
        stage=WorkflowStage.EXECUTE,
    )
    approval = await gate.request_approval(state=state, approval_type=ApprovalType.EXECUTION)
    assert state.approval_state == ApprovalState.PENDING
    assert await gate.requires_approval(state) == ApprovalType.EXECUTION

    approval.decision = ApprovalDecision.APPROVED
    approval.decided_by = ActorId(uuid.uuid4())
    await approvals.save_approval(approval)

    applied = await gate.apply_to_workflow(approval, state)
    assert applied.approval_state == ApprovalState.APPROVED
    assert await gate.requires_approval(state) is None


async def test_approval_gate_rejection_blocks() -> None:
    from brain.adapters.in_memory.policies import InMemoryApprovalRepository

    approvals = InMemoryApprovalRepository()
    gate = ApprovalGate(approvals=approvals)
    state = WorkflowState(
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=WorkItemId(uuid.uuid4()),
        stage=WorkflowStage.EXECUTE,
    )
    approval = await gate.request_approval(state=state, approval_type=ApprovalType.EXECUTION)
    approval.decision = ApprovalDecision.REJECTED
    approval.reason = "not now"
    await approvals.save_approval(approval)

    applied = await gate.apply_to_workflow(approval, state)
    assert applied.approval_state == ApprovalState.REJECTED
