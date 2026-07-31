from __future__ import annotations

import json
from dataclasses import dataclass

from agent_core.application.openproject_feedback import (
    OpenProjectFeedbackClassification,
    OpenProjectFeedbackIntent,
    classify_openproject_feedback,
)
from agent_core.domain.enums import ApprovalDecision, ApprovalScope
from agent_core.domain.events import EventEnvelope


@dataclass(frozen=True)
class OpenProjectApprovalDecision:
    approval_scope: ApprovalScope
    decision: ApprovalDecision
    reason: str


def classify_openproject_approval(
    envelope: EventEnvelope,
    feedback: OpenProjectFeedbackClassification | None = None,
) -> OpenProjectApprovalDecision | None:
    classification = feedback or classify_openproject_feedback(envelope)
    if classification.self_generated:
        return None

    decision = _decision_for_feedback_intent(classification.intent)
    if decision is None:
        return None

    return OpenProjectApprovalDecision(
        approval_scope=_approval_scope(envelope),
        decision=decision,
        reason=classification.reason,
    )


def _decision_for_feedback_intent(
    intent: OpenProjectFeedbackIntent,
) -> ApprovalDecision | None:
    if intent == OpenProjectFeedbackIntent.APPROVAL:
        return ApprovalDecision.APPROVED
    if intent in {
        OpenProjectFeedbackIntent.PLAN_FEEDBACK,
        OpenProjectFeedbackIntent.REQUIREMENT_CHANGE,
        OpenProjectFeedbackIntent.REWORK_REQUEST,
    }:
        return ApprovalDecision.CHANGES_REQUESTED
    if intent == OpenProjectFeedbackIntent.CANCELLATION:
        return ApprovalDecision.CANCELLED
    return None


def _approval_scope(envelope: EventEnvelope) -> ApprovalScope:
    text = json.dumps(envelope.payload, sort_keys=True, default=str).lower()
    task_markers = (
        "task completion",
        "completion approval",
        "completion",
        "task approved",
        "acceptance",
        "verification",
        "verified",
    )
    if any(marker in text for marker in task_markers):
        return ApprovalScope.TASK_COMPLETION
    return ApprovalScope.PLANNING
