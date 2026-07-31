from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from agent_core.domain.enums import ApprovalDecision, ApprovalScope


@dataclass(frozen=True)
class ApprovalRecordInput:
    project_id: UUID
    approval_scope: ApprovalScope
    decision: ApprovalDecision
    source_system: str = "openproject"
    source_event_id: str | None = None
    planning_session_id: UUID | None = None
    plan_version_id: UUID | None = None
    external_artifact_id: UUID | None = None
    external_project_id: str | None = None
    external_work_package_id: str | None = None
    external_comment_id: str | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class ApprovalRecordResult:
    approval_id: UUID
    project_id: UUID
    approval_scope: ApprovalScope
    decision: ApprovalDecision


class ApprovalRecordStorePort(Protocol):
    async def record(self, approval: ApprovalRecordInput) -> ApprovalRecordResult:
        ...
