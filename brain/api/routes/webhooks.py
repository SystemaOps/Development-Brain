"""OpenProject webhook routes (Phase 34, refactored).

Provider-specific input route: immediately validates, parses and normalizes
the payload to canonical events (Task 34.3).  The rest of the Brain only sees
canonical events — never OpenProject ``_embedded`` / ``_links`` structures.

Parsing follows ``docs/webhook/OPENPROJECT_WEBHOOK_PARSING_CONCISE.md`` and is
verified against the real payloads in ``docs/webhook/data.txt``:
``action`` is the discriminator; work items are normalized into snapshots and
ingested through the unified :class:`OpenProjectIngestionService` so webhook,
bootstrap, and pull share one canonical path (Phase 1.7).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from brain.api.auth import verify_webhook
from brain.api.dependencies import get_container
from brain.application.openproject_ingestion import (
    IngestionMode,
    OpenProjectIngestionResult,
    OpenProjectIngestionService,
)
from brain.application.openproject_parser import (
    parse_action,
    parse_attachment,
    parse_project,
    parse_work_item,
)
from brain.bootstrap.container import BrainContainer
from brain.domain.events import EventEnvelope, EventType
from brain.domain.external_reference import ExternalReference

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
    """Normalize a work-package event and trigger workflows (Phase 1.7)."""
    snapshot = parse_work_item(body)
    if snapshot is None:
        return {"accepted": False, "error": "no work_package"}

    service = container.services["openproject_ingestion"]
    assert isinstance(service, OpenProjectIngestionService)
    result = await service.ingest_work_item_snapshot(
        snapshot,
        mode=IngestionMode.LIVE,
        source="openproject.webhook",
        correlation_id=request.state.correlation_id,
        provider_action=action,
    )

    response: dict[str, object] = {
        "accepted": True,
        "event_type": result.event_type or "work_item_changed",
        "external_id": snapshot.external_id,
        "changes": [change.value for change in result.changes],
    }
    if result.assignment_triggered:
        response["triggered"] = "assignment"

    # Task 34.8: a human reply normalizes to HumanFeedbackReceived.
    comment = _extract_comment(body)
    if comment is not None:
        feedback_result = await _ingest_human_comment(
            container, result, comment, request.state.correlation_id
        )
        response["feedback"] = feedback_result

    # NOTE: persistence uses the container session (flushed, same-session
    # visibility); an explicit commit/unit-of-work boundary arrives with the
    # bootstrap/pull phases where atomic ingestion batches are introduced.
    return response


async def _ingest_human_comment(
    container: BrainContainer,
    result: OpenProjectIngestionResult,
    comment: dict[str, object],
    correlation_id: object,
) -> dict[str, object]:
    """Normalize a human comment through the unified ingestion service."""
    service = container.services["openproject_ingestion"]
    assert isinstance(service, OpenProjectIngestionService)
    work_item_id = result.work_item.id if result.work_item is not None else None

    ingested = await service.ingest_comment(
        work_item_id=work_item_id,
        external_id=str(comment.get("external_comment_id", "")),
        author_name=str(comment.get("author", "human")),
        text=str(comment.get("message", "")),
        mode=IngestionMode.LIVE,
        source="openproject.webhook",
    )
    return {
        "feedback_id": str(ingested.id),
        "normalized_to": "HumanFeedbackReceived",
        "work_item_id": str(work_item_id) if work_item_id is not None else None,
    }


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


__all__ = ["router"]
