from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent_core.domain.events import EventEnvelope

IDEMPOTENCY_MARKER_PREFIX = "ada:openproject-idempotency"


class OpenProjectFeedbackIntent(StrEnum):
    NONE = "none"
    GENERAL_COMMENT = "general_comment"
    REQUIREMENT_CHANGE = "requirement_change"
    PLAN_FEEDBACK = "plan_feedback"
    APPROVAL = "approval"
    REWORK_REQUEST = "rework_request"
    PAUSE = "pause"
    RESUME = "resume"
    CANCELLATION = "cancellation"
    AGENT_ECHO = "agent_echo"


@dataclass(frozen=True)
class OpenProjectFeedbackClassification:
    intent: OpenProjectFeedbackIntent
    resumable: bool
    self_generated: bool
    reason: str


def openproject_idempotency_marker(idempotency_key: str) -> str:
    return f"<!-- {IDEMPOTENCY_MARKER_PREFIX}: {idempotency_key} -->"


def markdown_with_idempotency_marker(markdown: str, idempotency_key: str) -> str:
    marker = openproject_idempotency_marker(idempotency_key)
    if marker in markdown:
        return markdown
    return f"{markdown.rstrip()}\n\n{marker}"


def has_openproject_idempotency_marker(
    text: str | None,
    idempotency_key: str | None = None,
) -> bool:
    if not text:
        return False
    if idempotency_key is None:
        return IDEMPOTENCY_MARKER_PREFIX in text
    return openproject_idempotency_marker(idempotency_key) in text


def classify_openproject_feedback(
    envelope: EventEnvelope,
) -> OpenProjectFeedbackClassification:
    text = _event_text(envelope)
    if has_openproject_idempotency_marker(text):
        return OpenProjectFeedbackClassification(
            intent=OpenProjectFeedbackIntent.AGENT_ECHO,
            resumable=False,
            self_generated=True,
            reason="OpenProject payload contains an agent idempotency marker",
        )

    event_type = envelope.event_type.lower()
    action = str(envelope.payload.get("action", "")).lower()
    combined = f"{event_type} {action} {text}"

    if any(marker in combined for marker in ("cancel", "cancelled", "canceled")):
        return _resumable(OpenProjectFeedbackIntent.CANCELLATION, "Cancellation feedback")
    if any(marker in combined for marker in ("pause", "paused", "hold")):
        return _resumable(OpenProjectFeedbackIntent.PAUSE, "Pause feedback")
    if any(marker in combined for marker in ("resume", "unblock", "continue")):
        return _resumable(OpenProjectFeedbackIntent.RESUME, "Resume feedback")
    if any(marker in combined for marker in ("rework", "changes required", "revise")):
        return _resumable(OpenProjectFeedbackIntent.REWORK_REQUEST, "Rework feedback")
    if any(marker in combined for marker in ("approve", "approved", "approval")):
        return _resumable(OpenProjectFeedbackIntent.APPROVAL, "Approval feedback")
    if "requirement" in combined and any(
        marker in combined for marker in ("change", "update", "missing", "add")
    ):
        return _resumable(
            OpenProjectFeedbackIntent.REQUIREMENT_CHANGE,
            "Requirement change feedback",
        )
    if any(marker in combined for marker in ("plan", "feedback", "clarify")):
        return _resumable(OpenProjectFeedbackIntent.PLAN_FEEDBACK, "Plan feedback")
    if envelope.external_comment_id or "comment" in combined:
        return _resumable(OpenProjectFeedbackIntent.GENERAL_COMMENT, "Human comment")

    return OpenProjectFeedbackClassification(
        intent=OpenProjectFeedbackIntent.NONE,
        resumable=False,
        self_generated=False,
        reason="No resumable OpenProject feedback marker found",
    )


def _resumable(
    intent: OpenProjectFeedbackIntent,
    reason: str,
) -> OpenProjectFeedbackClassification:
    return OpenProjectFeedbackClassification(
        intent=intent,
        resumable=True,
        self_generated=False,
        reason=reason,
    )


def _event_text(envelope: EventEnvelope) -> str:
    return json.dumps(envelope.payload, sort_keys=True, default=str).lower()
