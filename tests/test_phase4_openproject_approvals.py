from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from agent_core.application.openproject_approvals import (
    classify_openproject_approval,
)
from agent_core.domain.enums import ApprovalDecision, ApprovalScope
from agent_core.domain.events import EventEnvelope
from agent_core.models import ApprovalRecord
from agent_core.persistence.approvals import SqlAlchemyApprovalRecordStore
from agent_core.ports.approvals import ApprovalRecordInput


def test_approval_record_model_tracks_planning_and_task_completion_decisions():
    assert ApprovalRecord.__tablename__ == "approval_records"

    columns = ApprovalRecord.__table__.columns
    assert "project_id" in columns
    assert "planning_session_id" in columns
    assert "plan_version_id" in columns
    assert "external_artifact_id" in columns
    assert "approval_scope" in columns
    assert "decision" in columns
    assert "source_system" in columns
    assert "source_event_id" in columns
    assert "payload" in columns

    constraints = {constraint.name for constraint in ApprovalRecord.__table__.constraints}
    assert "ck_approval_records_scope" in constraints
    assert "ck_approval_records_decision" in constraints
    assert "uq_approval_records_source_decision" in constraints

    index_names = {index.name for index in ApprovalRecord.__table__.indexes}
    assert "idx_approval_records_project_scope" in index_names
    assert "idx_approval_records_source_event" in index_names


def test_openproject_approval_classifier_detects_planning_approval():
    decision = classify_openproject_approval(
        EventEnvelope(
            source="openproject",
            event_type="work_package.comment_created",
            external_comment_id="99",
            payload={"comment": {"raw": "Approved. Proceed with the plan."}},
        )
    )

    assert decision is not None
    assert decision.approval_scope == ApprovalScope.PLANNING
    assert decision.decision == ApprovalDecision.APPROVED


def test_openproject_approval_classifier_detects_task_completion_approval():
    decision = classify_openproject_approval(
        EventEnvelope(
            source="openproject",
            event_type="work_package.comment_created",
            external_work_package_id="34",
            external_comment_id="99",
            payload={"comment": {"raw": "Approved task completion."}},
        )
    )

    assert decision is not None
    assert decision.approval_scope == ApprovalScope.TASK_COMPLETION
    assert decision.decision == ApprovalDecision.APPROVED


def test_openproject_approval_classifier_records_rework_as_changes_requested():
    decision = classify_openproject_approval(
        EventEnvelope(
            source="openproject",
            event_type="work_package.comment_created",
            external_comment_id="99",
            payload={"comment": {"raw": "Changes required before plan approval."}},
        )
    )

    assert decision is not None
    assert decision.approval_scope == ApprovalScope.PLANNING
    assert decision.decision == ApprovalDecision.CHANGES_REQUESTED


class FakeSession:
    def __init__(self, scalar_results: list[Any]):
        self.scalar_results = scalar_results
        self.statements: list[Any] = []
        self.commits = 0

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.scalar_results.pop(0)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_approval_record_store_persists_audit_row():
    project_id = uuid4()
    session_id = uuid4()
    version_id = uuid4()
    artifact_id = uuid4()
    approval_id = uuid4()
    session = FakeSession([approval_id])

    result = await SqlAlchemyApprovalRecordStore(session).record(
        ApprovalRecordInput(
            project_id=project_id,
            planning_session_id=session_id,
            plan_version_id=version_id,
            external_artifact_id=artifact_id,
            approval_scope=ApprovalScope.PLANNING,
            decision=ApprovalDecision.APPROVED,
            source_event_id="event-1",
            external_project_id="12",
            external_work_package_id="34",
            external_comment_id="99",
            reason="Approval feedback",
            payload={"comment": {"raw": "Approved."}},
        )
    )

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (source_system, source_event_id, approval_scope, decision)" in compiled
    assert result.approval_id == approval_id
    assert result.project_id == project_id
    assert result.approval_scope == ApprovalScope.PLANNING
    assert result.decision == ApprovalDecision.APPROVED
    assert session.commits == 1


@pytest.mark.asyncio
async def test_approval_record_store_returns_existing_source_decision_record():
    existing_id = uuid4()
    project_id = uuid4()
    existing = type(
        "ExistingApproval",
        (),
        {
            "id": existing_id,
            "project_id": project_id,
            "approval_scope": ApprovalScope.PLANNING.value,
            "decision": ApprovalDecision.APPROVED.value,
        },
    )()
    session = FakeSession([None, existing])

    result = await SqlAlchemyApprovalRecordStore(session).record(
        ApprovalRecordInput(
            project_id=project_id,
            approval_scope=ApprovalScope.PLANNING,
            decision=ApprovalDecision.APPROVED,
            source_event_id="event-1",
            payload={"comment": {"raw": "Approved."}},
        )
    )

    assert result.approval_id == existing_id
    assert result.project_id == project_id
    assert result.approval_scope == ApprovalScope.PLANNING
    assert result.decision == ApprovalDecision.APPROVED
    assert session.commits == 1
