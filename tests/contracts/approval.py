"""ApprovalRepository contract (Phase 17)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import WorkflowId, WorkItemId
from brain.domain.policies import Approval, ApprovalDecision, ApprovalType
from brain.ports.policies import ApprovalRepository


def _approval() -> Approval:
    return Approval(
        approval_type=ApprovalType.EXECUTION,
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=WorkItemId(uuid.uuid4()),
    )


class ApprovalRepositoryContract:
    @pytest.fixture
    def approvals(self) -> ApprovalRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, approvals: ApprovalRepository) -> None:
        assert isinstance(approvals, ApprovalRepository)

    async def test_save_and_get_round_trip(self, approvals: ApprovalRepository) -> None:
        approval = _approval()
        await approvals.save_approval(approval)
        stored = await approvals.get_approval(approval.id)
        assert stored is not None
        assert stored.id == approval.id
        assert stored.approval_type == ApprovalType.EXECUTION
        assert stored.is_open

    async def test_get_missing_returns_none(self, approvals: ApprovalRepository) -> None:
        assert await approvals.get_approval(uuid.uuid4()) is None

    async def test_list_open_for_work_item(self, approvals: ApprovalRepository) -> None:
        approval = _approval()
        await approvals.save_approval(approval)
        assert approval.work_item_id is not None
        open_approvals = await approvals.list_open_for_work_item(approval.work_item_id)
        assert [a.id for a in open_approvals] == [approval.id]

        approval.decision = ApprovalDecision.APPROVED
        await approvals.save_approval(approval)
        assert await approvals.list_open_for_work_item(approval.work_item_id) == []

    async def test_list_for_workflow(self, approvals: ApprovalRepository) -> None:
        approval = _approval()
        await approvals.save_approval(approval)
        assert approval.workflow_id is not None
        listed = await approvals.list_for_workflow(approval.workflow_id)
        assert [a.id for a in listed] == [approval.id]

    async def test_update_decision(self, approvals: ApprovalRepository) -> None:
        approval = _approval()
        await approvals.save_approval(approval)
        approval.decision = ApprovalDecision.REJECTED
        approval.reason = "needs rework"
        await approvals.save_approval(approval)
        stored = await approvals.get_approval(approval.id)
        assert stored is not None
        assert stored.decision == ApprovalDecision.REJECTED
        assert stored.reason == "needs rework"
