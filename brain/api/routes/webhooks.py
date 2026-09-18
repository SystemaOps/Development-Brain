"""OpenProject webhook routes (Phase 34, refactored).

Provider-specific input route: immediately validates, parses and normalizes
the payload to canonical events (Task 34.3).  The rest of the Brain only sees
canonical events — never OpenProject ``_embedded`` / ``_links`` structures.

Parsing follows ``docs/webhook/OPENPROJECT_WEBHOOK_PARSING_CONCISE.md`` and is
verified against the real payloads in ``docs/webhook/data.txt``:
``action`` is the discriminator; work items are normalized into snapshots and
diffed against the previous snapshot to emit semantic changes (doc §14).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from brain.api.auth import verify_webhook
from brain.api.dependencies import get_container
from brain.application.openproject_parser import (
    OpenProjectWorkItemSnapshot,
    SemanticChange,
    diff_snapshots,
    event_type_for_action,
    parse_action,
    parse_attachment,
    parse_project,
    parse_work_item,
)
from brain.bootstrap.container import BrainContainer
from brain.domain.events import EventEnvelope, EventType
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import WorkItemId
from brain.domain.work_items import WorkItem
from brain.domain.work_management import IntegrationMapping

router = APIRouter()

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


@router.post("/api/v1/webhooks/openproject")
async def openproject_webhook(
    request: Request,
    verified: Annotated[Request, Depends(verify_webhook("openproject"))],
) -> dict[str, object]:
    """Parse an OpenProject webhook and dispatch by ``action`` (40.3 auth)."""
    del verified
    container: BrainContainer = get_container(request)
    body = await request.json()

    action = parse_action(body)
    LOGGER.info(f"openproject_webhook: {action=}")

    if not action:
        return {"accepted": False, "error": "missing action"}

    if action.startswith("work_package:"):
        return await _handle_work_package(container, request, action, body)

    if action.startswith("project:"):
        return await _handle_project(container, request, body)

    if action.startswith("attachment:"):
        return await _handle_attachment(container, request, body)

    return {"accepted": True, "event_type": "ignored", "action": action}


async def _handle_work_package(
    container: BrainContainer,
    request: Request,
    action: str,
    body: dict[str, object],
) -> dict[str, object]:
    """Normalize a work-package event, diff it and trigger workflows."""
    snapshot = parse_work_item(body)
    if snapshot is None:
        return {"accepted": False, "error": "no work_package"}

    previous = await container.openproject_snapshots.get(snapshot.external_id)
    changes = diff_snapshots(previous, snapshot)
    await container.openproject_snapshots.save(snapshot)

    # Phase 2.1: emit typed canonical events so projections/handlers can
    # consume them (work_package:created -> WorkItemCreated, else
    # WorkItemChanged), folding the semantic changes into the payload.
    from brain.domain.event_types import WorkItemChanged, WorkItemCreated, model_to_envelope

    work_item = await _find_or_create_work_item(container, snapshot)
    if work_item is not None:
        typed_event = (
            WorkItemCreated(work_item=work_item)
            if action == "work_package:created"
            else WorkItemChanged(work_item=work_item)
        )
        envelope = model_to_envelope(
            typed_event,
            source="openproject.webhook",
            correlation_id=request.state.correlation_id,
        )
        envelope.payload["changes"] = [change.value for change in changes]
        envelope.payload["snapshot"] = _snapshot_payload(snapshot)
        envelope.payload["external_id"] = snapshot.external_id
    else:
        event_type = event_type_for_action(action) or EventType.WORK_ITEM_CHANGED
        envelope = EventEnvelope(
            event_type=event_type,
            correlation_id=request.state.correlation_id,
            source="openproject.webhook",
            payload={
                "provider": "openproject",
                "external_id": snapshot.external_id,
                "subject": snapshot.summary,
                "status": snapshot.state,
                "assignee": snapshot.assignee_id,
                "changes": [change.value for change in changes],
                "snapshot": _snapshot_payload(snapshot),
            },
        )
    await container.event_bus.publish(envelope)

    result: dict[str, object] = {
        "accepted": True,
        "event_type": envelope.event_type.value,
        "external_id": snapshot.external_id,
        "changes": [change.value for change in changes],
    }

    # Task 34.8: a human reply normalizes to HumanFeedbackReceived.
    comment = _extract_comment(body)
    if comment is not None:
        feedback_result = await _normalize_human_comment(container, snapshot.external_id, comment)
        result["feedback"] = feedback_result
        return result

    LOGGER.info(f"_handle_work_package: {comment=}")
    # Task 34.6 + doc §6 + event_command_flow: the webhook only reports the
    # assignment fact (WorkItemAssigned); the WorkItemAssignedHandler decides
    # the consequence (enqueue RUN_WORK_ITEM).
    assigned_to_brain = _is_assigned_to_brain(container, snapshot.assignee_id)
    newly_assigned = action == "work_package:created" or _has_change(changes, "assignee_changed")
    if assigned_to_brain and newly_assigned and snapshot.external_id and work_item is not None:
        from brain.domain.event_types import WorkItemAssigned
        from brain.domain.event_types import model_to_envelope as _m2e

        await container.event_bus.publish(
            _m2e(
                WorkItemAssigned(
                    work_item_id=work_item.id,
                    external_actor_id=snapshot.assignee_id,
                ),
                source="openproject.webhook",
                correlation_id=request.state.correlation_id,
            )
        )
        result["triggered"] = "assignment"
    return result


async def _handle_project(
    container: BrainContainer,
    request: Request,
    body: dict[str, object],
) -> dict[str, object]:
    """Normalize a project event and publish PROJECT_CHANGED."""
    project = parse_project(body)

    LOGGER.info(f"_handle_project: {project=}")
    if not project:
        return {"accepted": False, "error": "no project"}

    envelope = EventEnvelope(
        event_type=EventType.PROJECT_CHANGED,
        correlation_id=request.state.correlation_id,
        source="openproject.webhook",
        payload={
            "provider": "openproject",
            "external_id": project["external_id"],
            "name": project["name"],
            "identifier": project["identifier"],
            "active": project["active"],
            "parent_id": project["parent_id"],
        },
    )
    await container.event_bus.publish(envelope)
    return {
        "accepted": True,
        "event_type": EventType.PROJECT_CHANGED.value,
        "external_id": project["external_id"],
    }


async def _handle_attachment(
    container: BrainContainer,
    request: Request,
    body: dict[str, object],
) -> dict[str, object]:
    """Normalize an attachment event and publish ATTACHMENT_CREATED."""
    attachment = parse_attachment(body)
    if not attachment:
        return {"accepted": False, "error": "no attachment"}

    LOGGER.info(f"_handle_project: {attachment=}")

    envelope = EventEnvelope(
        event_type=EventType.ATTACHMENT_CREATED,
        correlation_id=request.state.correlation_id,
        source="openproject.webhook",
        payload={
            "provider": "openproject",
            "external_id": attachment["external_id"],
            "file_name": attachment["file_name"],
            "content_type": attachment["content_type"],
            "file_size": attachment["file_size"],
            "download_url": attachment["download_url"],
            "work_item_id": attachment["work_item_id"],
        },
    )
    await container.event_bus.publish(envelope)
    return {
        "accepted": True,
        "event_type": EventType.ATTACHMENT_CREATED.value,
        "external_id": attachment["external_id"],
        "work_item_id": attachment["work_item_id"],
    }


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
    # The webhook only reports the PullRequestMerged fact; the
    # PullRequestMergedHandler decides the consequences (revision changed +
    # re-ingestion).
    from brain.domain.event_types import PullRequestMerged, model_to_envelope

    envelope = model_to_envelope(
        PullRequestMerged(external_ref=ref),
        source="openproject.webhook",
        correlation_id=request.state.correlation_id,
    )
    await container.event_bus.publish(envelope)
    return {
        "accepted": True,
        "event_type": envelope.event_type.value,
        "external_id": ref.external_id,
    }


def _has_change(changes: list[SemanticChange], value: str) -> bool:
    return any(change.value == value for change in changes)


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


def _is_assigned_to_brain(container: BrainContainer, assignee_id: str | None) -> bool:
    brain_actor = container.settings.work_management.brain_actor_id
    if not brain_actor:
        return False
    return bool(assignee_id) and str(assignee_id) == str(brain_actor)


def _snapshot_payload(
    snapshot: OpenProjectWorkItemSnapshot,
) -> dict[str, object]:
    """Serialize a parsed snapshot into the envelope payload."""
    return {
        "type": snapshot.type,
        "priority": snapshot.priority,
        "closed": snapshot.closed,
        "project_id": snapshot.project_id,
        "project_name": snapshot.project_name,
        "assignee_name": snapshot.assignee_name,
        "parent_id": snapshot.parent_id,
        "attachments": snapshot.attachments,
        "relations": snapshot.relations,
        "activities_url": snapshot.activities_url,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


async def _find_or_create_work_item(
    container: BrainContainer,
    snapshot: OpenProjectWorkItemSnapshot,
) -> WorkItem | None:
    """Resolve the canonical work item for an external package (idempotent).

    The integration mapping (Task 34.4) is the source of truth: an existing
    mapping returns the same canonical work item instead of creating a
    duplicate on every webhook delivery.
    """
    existing_id = await _work_item_id_for_external(container, snapshot.external_id)
    if existing_id is not None:
        existing = await container.repositories.work_items.get(existing_id)
        if existing is not None:
            return existing

    project = None
    for candidate in await container.repositories.projects.list():
        project = candidate
        break
    if project is None:
        return None

    ref = ExternalReference(
        provider="openproject",
        external_id=snapshot.external_id,
        external_type="work_package",
    )
    work_item = WorkItem(
        project_id=project.id,
        title=str(snapshot.summary or f"OpenProject {snapshot.external_id}"),
        description=snapshot.description,
        external_refs=[ref],
    )
    created = await container.repositories.work_items.create(work_item)
    mapping = IntegrationMapping(
        work_item_id=created.id, provider="openproject", external_id=snapshot.external_id
    )
    await container.repositories.work_management_integrations.save_mapping(mapping)
    return created


__all__ = ["router"]
