from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.enums import ApprovalDecision, ApprovalScope
from agent_core.models import ApprovalRecord
from agent_core.ports.approvals import ApprovalRecordInput, ApprovalRecordResult


class SqlAlchemyApprovalRecordStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(self, approval: ApprovalRecordInput) -> ApprovalRecordResult:
        approval_id = uuid4()
        stmt = (
            insert(ApprovalRecord)
            .values(
                id=approval_id,
                project_id=approval.project_id,
                planning_session_id=approval.planning_session_id,
                plan_version_id=approval.plan_version_id,
                external_artifact_id=approval.external_artifact_id,
                source_system=approval.source_system,
                source_event_id=approval.source_event_id,
                external_project_id=approval.external_project_id,
                external_work_package_id=approval.external_work_package_id,
                external_comment_id=approval.external_comment_id,
                approval_scope=approval.approval_scope.value,
                decision=approval.decision.value,
                reason=approval.reason,
                payload=approval.payload or {},
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ApprovalRecord.source_system,
                    ApprovalRecord.source_event_id,
                    ApprovalRecord.approval_scope,
                    ApprovalRecord.decision,
                ]
            )
            .returning(ApprovalRecord.id)
        )
        inserted_id = await self.db.scalar(stmt)
        result_project_id = approval.project_id
        result_scope = approval.approval_scope
        result_decision = approval.decision
        if inserted_id is None:
            existing = await self.db.scalar(
                select(ApprovalRecord).where(
                    ApprovalRecord.source_system == approval.source_system,
                    ApprovalRecord.source_event_id == approval.source_event_id,
                    ApprovalRecord.approval_scope == approval.approval_scope.value,
                    ApprovalRecord.decision == approval.decision.value,
                )
            )
            if existing is None:
                raise RuntimeError(
                    "Approval record conflict did not find existing record"
                )
            approval_id = existing.id
            result_project_id = existing.project_id
            result_scope = ApprovalScope(existing.approval_scope)
            result_decision = ApprovalDecision(existing.decision)
        else:
            approval_id = inserted_id
        await self.db.commit()
        return ApprovalRecordResult(
            approval_id=approval_id,
            project_id=result_project_id,
            approval_scope=result_scope,
            decision=result_decision,
        )
