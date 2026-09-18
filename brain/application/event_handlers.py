"""Event handlers — the decision layer of the event→command flow.

Documented in ``docs/eventbus/event_command_flow.md``: webhooks produce facts,
these handlers decide consequences.  Each handler reacts to a typed canonical
event and either updates state, enqueues a command, or both.

Handlers receive the container so they can reach repositories, the command
queue and application services (same pattern as PullRequestService).
"""

from __future__ import annotations

from brain.application.human_feedback import HumanFeedbackService
from brain.bootstrap.container import BrainContainer
from brain.domain.commands import (
    CommandType,
    RunWorkItemCommand,
    TriggerType,
    make_command,
)
from brain.domain.event_types import (
    HumanFeedbackReceived,
    PullRequestMerged,
    WorkItemAssigned,
    event_to_model,
)
from brain.domain.events import EventEnvelope
from brain.domain.human_activity import HumanFeedback
from brain.ports.commands import CommandQueue
from brain.ports.event_bus import EventHandler


class WorkItemAssignedHandler(EventHandler):
    """Consequence of assignment: run the work item.

    The webhook only reports ``WorkItemAssigned``; this handler decides that a
    workflow must run and enqueues ``RUN_WORK_ITEM``.
    """

    def __init__(self, container: BrainContainer) -> None:
        self._container = container

    async def handle(self, event: EventEnvelope) -> None:
        model = event_to_model(event)
        if not isinstance(model, WorkItemAssigned):
            return
        queue = self._container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.RUN_WORK_ITEM,
                RunWorkItemCommand(work_item_id=model.work_item_id),
                trigger_type=TriggerType.EVENT,
                correlation_id=event.correlation_id,
            )
        )


class HumanFeedbackReceivedHandler(EventHandler):
    """Consequence of human feedback: resume the waiting workflow.

    The fact ``HumanFeedbackReceived`` is emitted by
    :class:`HumanFeedbackService`; this handler applies the consequence
    (store feedback, invalidate stale context, resume) without re-emitting.
    """

    def __init__(self, container: BrainContainer) -> None:
        self._container = container

    async def handle(self, event: EventEnvelope) -> None:
        model = event_to_model(event)
        if not isinstance(model, HumanFeedbackReceived):
            return
        service = self._container.services["human_feedback"]
        assert isinstance(service, HumanFeedbackService)
        feedback = HumanFeedback(
            author=model.author,
            provider=model.provider,
            external_comment_id=model.external_comment_id,
            work_item_id=model.work_item_id,
            message=model.feedback,
        )
        await service.resume_workflow(feedback, verdict=model.verdict.value)


class PullRequestMergedHandler(EventHandler):
    """Consequence of a merge: re-ingest the merged revision.

    The webhook reports ``PullRequestMerged``; this handler publishes
    ``RepositoryRevisionChanged`` and enqueues re-ingestion.
    """

    def __init__(self, container: BrainContainer) -> None:
        self._container = container

    async def handle(self, event: EventEnvelope) -> None:
        model = event_to_model(event)
        if not isinstance(model, PullRequestMerged):
            return
        service = self._container.services["pull_request_service"]
        from brain.application.pull_request_service import PullRequestService

        assert isinstance(service, PullRequestService)
        await service.apply_merge_consequences(
            model.external_ref, correlation_id=event.correlation_id
        )


__all__ = [
    "HumanFeedbackReceivedHandler",
    "PullRequestMergedHandler",
    "WorkItemAssignedHandler",
]
