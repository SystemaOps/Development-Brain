"""OpenProject webhook routes (Phase 34).

Provider-specific input route: immediately validates and normalizes the
payload to canonical events (Task 34.3).  The rest of the Brain only sees
canonical events.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from brain.api.auth import verify_webhook
from brain.api.commands import enqueue_command
from brain.api.dependencies import get_container
from brain.bootstrap.container import BrainContainer
from brain.domain.commands import CommandType, RunWorkItemCommand
from brain.domain.events import EventEnvelope, EventType
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import WorkItemId
from brain.domain.work_items import WorkItem
from brain.domain.work_management import IntegrationMapping

router = APIRouter()

_EVENT_TYPES = {
    "work_package:created": EventType.WORK_ITEM_CREATED,
    "work_package:updated": EventType.WORK_ITEM_CHANGED,
}


@router.post("/api/v1/webhooks/openproject")
async def openproject_webhook(
    request: Request,
    verified: Annotated[Request, Depends(verify_webhook("openproject"))],
) -> dict[str, object]:
    """Normalize an OpenProject webhook to a canonical event (40.3 auth)."""
    del verified
    container: BrainContainer = get_container(request)
    body = await request.json()
    event_type_name = str(body.get("eventType") or body.get("event_type") or "")
    work_package = body.get("work_package") or body.get("workPackage") or {}

    external_id = str(work_package.get("id") or work_package.get("_id") or "")
    event_type = _EVENT_TYPES.get(event_type_name, EventType.WORK_ITEM_CHANGED)

    envelope = EventEnvelope(
        event_type=event_type,
        correlation_id=request.state.correlation_id,
        source="openproject.webhook",
        payload={
            "provider": "openproject",
            "external_id": external_id,
            "subject": work_package.get("subject", ""),
            "status": work_package.get("status", ""),
            "assignee": _assignee_id(work_package),
        },
    )
    await container.event_bus.publish(envelope)

    result: dict[str, object] = {
        "accepted": True,
        "event_type": event_type.value,
        "external_id": external_id,
    }

    # Task 34.8: a human reply (comment activity) normalizes to
    # HumanFeedbackReceived.
    comment = _extract_comment(body)
    if comment is not None:
        feedback_result = await _normalize_human_comment(container, external_id, comment)
        result["feedback"] = feedback_result
        return result

    # Task 34.6: assignment automation.  If the package was assigned to the
    # Brain actor, enqueue RunWorkItemCommand.
    assigned_to_brain = _is_assigned_to_brain(container, work_package)
    if assigned_to_brain and external_id:
        work_item = await _find_or_create_work_item(container, envelope, external_id)
        if work_item is not None:
            accepted = await enqueue_command(
                container,
                CommandType.RUN_WORK_ITEM,
                RunWorkItemCommand(work_item_id=work_item.id),
                correlation_id=request.state.correlation_id,
            )
            result["command_id"] = accepted.command_id
            result["triggered"] = "assignment"
    return result


@router.post("/api/v1/webhooks/gitlab")
async def gitlab_webhook(
    request: Request,
    verified: Annotated[Request, Depends(verify_webhook("gitlab"))],
) -> dict[str, object]:
    """Normalize a GitLab merge-request webhook (Task 38.5, 40.3 auth).

    A ``merge`` event on a merge request normalizes to PullRequestMerged ->
    RepositoryRevisionChanged and re-ingestion is enqueued so merged code
    returns into Brain knowledge.
    """
    del verified
    container: BrainContainer = get_container(request)
    body = await request.json()
    object_kind = str(body.get("object_kind") or "")
    if object_kind != "merge_request":
        return {"accepted": True, "event_type": "ignored", "kind": object_kind}

    attributes = body.get("object_attributes") or {}
    state = str(attributes.get("state") or "")
    if state != "merged":
        return {"accepted": True, "event_type": "ignored", "state": state}

    ref = ExternalReference(
        provider="gitlab",
        external_id=str(attributes.get("iid") or ""),
        external_type="merge_request",
        namespace=str(attributes.get("target_project_id") or ""),
    )
    service = container.services["pull_request_service"]
    from brain.application.pull_request_service import PullRequestService

    assert isinstance(service, PullRequestService)
    envelope = await service.handle_merge(ref)
    return {
        "accepted": True,
        "event_type": envelope.event_type.value,
        "external_id": ref.external_id,
    }


def _extract_comment(body: dict[str, object]) -> dict[str, object] | None:
    """Extract a comment/activity payload from an OpenProject webhook, if any."""
    comment = body.get("comment")
    activity = body.get("activity")
    raw = None
    if isinstance(comment, dict):
        raw = comment
    elif isinstance(activity, dict):
        raw = activity
    if raw is None:
        return None
    message = str(raw.get("raw") or raw.get("comment") or raw.get("text") or "").strip()
    if not message:
        return None
    author = raw.get("author") or raw.get("user") or {}
    author_name = ""
    if isinstance(author, dict):
        author_name = str(author.get("name") or author.get("id") or "")
    return {
        "author": author_name or "human",
        "message": message,
        "external_comment_id": str(raw.get("id") or ""),
    }


async def _normalize_human_comment(
    container: BrainContainer, external_id: str, comment: dict[str, object]
) -> dict[str, object]:
    """Normalize a human comment to HumanFeedbackReceived and resume."""
    from brain.application.human_feedback import HumanFeedbackService

    service = container.services["human_feedback"]
    assert isinstance(service, HumanFeedbackService)

    # Resolve the canonical work item via the external mapping (Task 34.4).
    work_item_id = await _work_item_id_for_external(container, external_id)
    feedback = await service.receive(
        author=str(comment.get("author", "human")),
        provider="openproject",
        external_comment_id=str(comment.get("external_comment_id", "")),
        work_item_id=work_item_id,
        message=str(comment.get("message", "")),
        verdict="note",
    )
    return {
        "feedback_id": str(feedback.id),
        "normalized_to": "HumanFeedbackReceived",
        "work_item_id": str(work_item_id) if work_item_id else None,
    }


async def _work_item_id_for_external(
    container: BrainContainer, external_id: str
) -> WorkItemId | None:
    """Find the canonical work item id for an external package id."""
    for project in await container.repositories.projects.list():
        for work_item in await container.repositories.work_items.list_by_project(project.id):
            for ref in work_item.external_refs:
                if ref.provider == "openproject" and ref.external_id == external_id:
                    return work_item.id
    return None


def _assignee_id(work_package: dict[str, object]) -> str:
    assignee = work_package.get("assignee") or {}
    if isinstance(assignee, dict):
        href = str(assignee.get("href", ""))
        if href:
            return href.rsplit("/", 1)[-1]
    return ""


def _is_assigned_to_brain(container: BrainContainer, work_package: dict[str, object]) -> bool:
    brain_actor = container.settings.work_management.brain_actor_id
    if not brain_actor:
        return False
    return _assignee_id(work_package) == str(brain_actor)


async def _find_or_create_work_item(
    container: BrainContainer, envelope: EventEnvelope, external_id: str
) -> WorkItem | None:
    """Resolve the canonical work item for an external package."""
    project = None
    for candidate in await container.repositories.projects.list():
        project = candidate
        break
    if project is None:
        return None

    ref = ExternalReference(
        provider="openproject", external_id=external_id, external_type="work_package"
    )
    work_item = WorkItem(
        project_id=project.id,
        title=str(envelope.payload.get("subject") or f"OpenProject {external_id}"),
        external_refs=[ref],
    )
    created = await container.repositories.work_items.create(work_item)
    mapping = IntegrationMapping(
        work_item_id=created.id, provider="openproject", external_id=external_id
    )
    await container.repositories.work_management_integrations.save_mapping(mapping)
    return created


__all__ = ["router"]
