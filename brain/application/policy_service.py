"""Policy service (Phase 17).

Deterministic risk classification (Task 17.5), policy evaluation that derives
executor permissions and approval requirements (Tasks 17.1, 17.2, 17.4), and
approval decision application that unblocks workflows (Task 17.6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from brain.domain.executions import ExecutionPermissions
from brain.domain.identity import ActorId, WorkflowId, WorkItemId
from brain.domain.policies import (
    Approval,
    ApprovalDecision,
    ApprovalType,
    PolicyAction,
    RiskLevel,
)
from brain.domain.work_items import WorkItem
from brain.ports.policies import PolicyProvider

_HIGH_RISK_PATTERNS = [
    re.compile(r"\b(migrations?|alembic|schema change)\b", re.IGNORECASE),
    re.compile(r"\b(authentication|authn|login|oauth|sso)\b", re.IGNORECASE),
    re.compile(r"\b(authorization|authz|rbac|permissions?|role)\b", re.IGNORECASE),
    re.compile(r"\b(crypto|encryption|signature|cipher)\b", re.IGNORECASE),
    re.compile(r"\b(billing|payment|invoice|charge|stripe)\b", re.IGNORECASE),
    re.compile(r"\b(production|deploy|infrastructure|kubernetes|terraform)\b", re.IGNORECASE),
    re.compile(r"\b(secret|credential|token|api[_-]?key)\b", re.IGNORECASE),
    re.compile(r"\b(drop |truncate |delete |destructive)\b", re.IGNORECASE),
]

_MEDIUM_RISK_PATTERNS = [
    re.compile(r"\b(database|sql|query|model)\b", re.IGNORECASE),
    re.compile(r"\b(api|endpoint|http|rest)\b", re.IGNORECASE),
    re.compile(r"\b(cache|redis|queue|kafka)\b", re.IGNORECASE),
]


@dataclass
class RiskAssessment:
    risk: RiskLevel
    reasons: list[str] = field(default_factory=list)


@dataclass
class PolicyEvaluation:
    permissions: ExecutionPermissions
    required_approvals: list[ApprovalType] = field(default_factory=list)
    allowed: bool = True
    reasons: list[str] = field(default_factory=list)


class PolicyService:
    """Classify risk and apply configured policies."""

    def __init__(self, *, policies: PolicyProvider) -> None:
        self._policies = policies

    async def classify_risk(
        self, work_item: WorkItem | None, *, title: str = "", description: str = ""
    ) -> RiskAssessment:
        text = " ".join(
            [
                work_item.title if work_item else "",
                work_item.description if work_item else "",
                title,
                description,
            ]
        )
        reasons: list[str] = []
        for pattern in _HIGH_RISK_PATTERNS:
            if pattern.search(text):
                reasons.append(f"high-risk signal: {pattern.pattern}")
        if reasons:
            return RiskAssessment(risk=RiskLevel.HIGH, reasons=reasons)

        for pattern in _MEDIUM_RISK_PATTERNS:
            if pattern.search(text):
                reasons.append(f"medium-risk signal: {pattern.pattern}")
        if reasons:
            return RiskAssessment(risk=RiskLevel.MEDIUM, reasons=reasons)

        return RiskAssessment(risk=RiskLevel.LOW)

    async def evaluate(
        self,
        work_item: WorkItem | None,
        *,
        title: str = "",
        description: str = "",
    ) -> PolicyEvaluation:
        assessment = await self.classify_risk(work_item, title=title, description=description)
        policy_set = await self._policies.get_policy_set()
        permissions = ExecutionPermissions()
        approvals: list[ApprovalType] = []
        allowed = True
        reasons: list[str] = []

        for rule in policy_set.rules_for_risk(assessment.risk):
            if rule.permissions is not None:
                permissions = _merge_permissions(permissions, rule.permissions)
            if rule.action == PolicyAction.REQUIRE_APPROVAL and rule.approval_type is not None:
                approvals.append(rule.approval_type)
            if rule.action == PolicyAction.DENY:
                allowed = False
            reasons.append(rule.name)

        if not reasons:
            reasons.append(f"no policies matched risk {assessment.risk.value}")

        return PolicyEvaluation(
            permissions=permissions,
            required_approvals=approvals,
            allowed=allowed,
            reasons=reasons,
        )

    async def request_approval(
        self,
        *,
        approval_type: ApprovalType,
        workflow_id: WorkflowId,
        work_item_id: WorkItemId,
        requested_by: ActorId | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Approval:
        approval = Approval(
            approval_type=approval_type,
            workflow_id=workflow_id,
            work_item_id=work_item_id,
            requested_by=requested_by,
            metadata=metadata or {},
        )
        return approval

    async def decide_approval(
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
        approval.decided_at = datetime.now(UTC)
        return approval


def _merge_permissions(
    base: ExecutionPermissions, override: ExecutionPermissions
) -> ExecutionPermissions:
    return ExecutionPermissions(
        repository_read=base.repository_read or override.repository_read,
        repository_write=base.repository_write or override.repository_write,
        shell=base.shell or override.shell,
        network=base.network or override.network,
        git_commit=base.git_commit or override.git_commit,
        git_push=base.git_push or override.git_push,
        create_pull_request=base.create_pull_request or override.create_pull_request,
        merge_pull_request=base.merge_pull_request or override.merge_pull_request,
        run_containers=base.run_containers or override.run_containers,
        access_secrets=base.access_secrets or override.access_secrets,
        deploy=base.deploy or override.deploy,
    )


__all__ = ["PolicyEvaluation", "PolicyService", "RiskAssessment"]
