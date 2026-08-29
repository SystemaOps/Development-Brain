"""Human feedback normalization and resume service (Phase 27).

Human replies in OpenProject/Jira/XWiki are normalized to
``HumanFeedbackReceived`` (Task 27.7).  When a workflow waits for human input,
the feedback is stored, stale context is invalidated, and the workflow resumes
(Task 27.8).
"""

from __future__ import annotations

import logging
import uuid

from brain.domain.events import EventEnvelope, EventType
from brain.domain.human_activity import HumanFeedback
from brain.domain.identity import WorkItemId
from brain.ports.context import ContextCapsuleRepository
from brain.ports.event_bus import EventBus
from brain.ports.repositories import (
    DecisionRepository,
    RequirementRepository,
    WorkItemRepository,
)

logger = logging.getLogger(__name__)


class HumanFeedbackService:
    """Normalizes human replies and resumes waiting workflows."""

    def __init__(
        self,
        *,
        work_items: WorkItemRepository,
        requirements: RequirementRepository,
        decisions: DecisionRepository,
        capsules: ContextCapsuleRepository,
        event_bus: EventBus,
    ) -> None:
        self._work_items = work_items
        self._requirements = requirements
        self._decisions = decisions
        self._capsules = capsules
        self._event_bus = event_bus

    async def receive(
        self,
        *,
        author: str,
        provider: str,
        external_comment_id: str,
        work_item_id: WorkItemId | None,
        message: str,
        verdict: str = "note",
    ) -> HumanFeedback:
        """Normalize a human reply to ``HumanFeedbackReceived`` (Task 27.7)."""
        feedback = HumanFeedback(
            author=author,
            provider=provider,
            external_comment_id=external_comment_id,
            work_item_id=work_item_id,
            message=message,
        )
        await self._emit(feedback, verdict=verdict)
        return feedback

    async def resume_workflow(
        self,
        feedback: HumanFeedback,
        *,
        verdict: str = "note",
    ) -> dict[str, object]:
        """Apply feedback: store, invalidate stale context, resume (Task 27.8)."""
        if feedback.work_item_id is None:
            return {"status": "no_work_item"}

        work_item_id = WorkItemId(feedback.work_item_id)
        work_item = await self._work_items.get(work_item_id)
        if work_item is None:
            return {"work_item_id": feedback.work_item_id, "status": "not_found"}

        # Invalidate stale context capsules for the work item.
        for capsule in await self._capsules.list_capsules_for_work_item(work_item_id):
            await self._capsules.delete_capsule(capsule.id)

        await self._emit(feedback, verdict=verdict)
        return {
            "work_item_id": feedback.work_item_id,
            "status": "resumed",
            "context_invalidated": True,
        }

    async def _emit(self, feedback: HumanFeedback, *, verdict: str) -> None:
        envelope = EventEnvelope(
            event_type=EventType.HUMAN_FEEDBACK_RECEIVED,
            correlation_id=uuid.uuid4(),
            source=f"brain.human_feedback.{feedback.provider}",
            payload={
                "author": feedback.author,
                "provider": feedback.provider,
                "external_comment_id": feedback.external_comment_id,
                "work_item_id": str(feedback.work_item_id) if feedback.work_item_id else None,
                "message": feedback.message,
                "verdict": verdict,
            },
        )
        await self._event_bus.publish(envelope)


__all__ = ["HumanFeedbackService"]
