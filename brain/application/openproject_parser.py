"""OpenProject webhook parsing (Phase A).

Pure functions that turn raw OpenProject webhook bodies into normalized
snapshots and semantic change events, following
``docs/webhook/OPENPROJECT_WEBHOOK_PARSING_CONCISE.md``.

The parser has no I/O and never imports orchestrator modules: the rest of the
Brain only ever sees normalized snapshots, never ``_embedded`` / ``_links``
structures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from brain.domain.events import EventType


class SemanticChange(StrEnum):
    """A field-level change detected by comparing two snapshots (doc §14)."""

    SUMMARY_CHANGED = "summary_changed"
    DESCRIPTION_CHANGED = "description_changed"
    ASSIGNEE_CHANGED = "assignee_changed"
    STATE_CHANGED = "state_changed"
    PRIORITY_CHANGED = "priority_changed"
    PARENT_CHANGED = "parent_changed"


@dataclass(frozen=True)
class OpenProjectWorkItemSnapshot:
    """Normalized work-package snapshot (doc §2)."""

    external_id: str
    summary: str = ""
    description: str = ""
    type: str = ""
    priority: str = ""
    state: str = ""
    closed: bool = False
    project_id: str | None = None
    project_name: str | None = None
    assignee_id: str | None = None
    assignee_name: str | None = None
    parent_id: int | None = None
    attachments: list[dict[str, object]] = field(default_factory=list)
    relations: list[dict[str, object]] = field(default_factory=list)
    activities_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def parse_action(body: dict[str, object]) -> str:
    """Return the webhook action, honoring ``action`` first (doc §1).

    ``eventType`` / ``event_type`` are accepted as a fallback for payloads
    produced by older clients or tests.
    """
    action = body.get("action")
    if isinstance(action, str) and action:
        return action
    event_type = body.get("eventType") or body.get("event_type")
    return str(event_type) if event_type else ""


def id_from_href(href: str | None) -> int | None:
    """Extract the trailing numeric id from an OpenProject href (doc §7)."""
    if not href:
        return None
    try:
        return int(href.rstrip("/").split("/")[-1])
    except ValueError:
        return None


def parse_work_item(body: dict[str, object]) -> OpenProjectWorkItemSnapshot | None:
    """Normalize a ``work_package`` payload to a snapshot (doc §2, §16).

    Returns ``None`` when the body has no usable ``work_package``.
    """
    wp = body.get("work_package")
    if not isinstance(wp, dict):
        return None
    embedded = _as_dict(wp.get("_embedded"))
    links = _as_dict(wp.get("_links"))

    external_id = str(wp.get("id") or wp.get("_id") or "")
    if not external_id:
        return None

    type_ = _as_dict(embedded.get("type"))
    priority = _as_dict(embedded.get("priority"))
    status = _as_dict(embedded.get("status"))
    project = _as_dict(embedded.get("project"))
    assignee = _as_dict(embedded.get("assignee")) if embedded.get("assignee") is not None else None

    description = wp.get("description")
    description_raw = ""
    if isinstance(description, dict):
        description_raw = str(description.get("raw") or "")

    attachments = _as_dict(embedded.get("attachments"))
    relations = _as_dict(embedded.get("relations"))
    attachment_elements = _as_dict(attachments.get("_embedded")).get("elements") or []
    relation_elements = _as_dict(relations.get("_embedded")).get("elements") or []

    return OpenProjectWorkItemSnapshot(
        external_id=external_id,
        summary=str(wp.get("subject") or ""),
        description=description_raw,
        type=str(type_.get("name") or ""),
        priority=str(priority.get("name") or ""),
        state=str(status.get("name") or ""),
        closed=bool(status.get("isClosed") or False),
        project_id=str(project.get("id")) if project.get("id") is not None else None,
        project_name=str(project.get("name")) if project.get("name") is not None else None,
        assignee_id=str(assignee.get("id"))
        if assignee and assignee.get("id") is not None
        else None,
        assignee_name=(
            str(assignee.get("name")) if assignee and assignee.get("name") is not None else None
        ),
        parent_id=id_from_href(_optional_str(_as_dict(links.get("parent")).get("href"))),
        attachments=_normalize_attachments(attachment_elements),
        relations=_normalize_relations(relation_elements),
        activities_url=_optional_str(_as_dict(links.get("activities")).get("href")),
        created_at=_optional_str(wp.get("createdAt")),
        updated_at=_optional_str(wp.get("updatedAt")),
    )


def parse_project(body: dict[str, object]) -> dict[str, object]:
    """Normalize a ``project:created`` / ``project:updated`` payload (doc §12)."""
    project = body.get("project")
    if not isinstance(project, dict):
        return {}
    embedded = _as_dict(project.get("_embedded"))
    parent = _as_dict(embedded.get("parent")) if embedded.get("parent") is not None else None
    return {
        "external_id": str(project.get("id") or ""),
        "name": str(project.get("name") or ""),
        "identifier": str(project.get("identifier") or ""),
        "active": bool(project.get("active") or False),
        "parent_id": str(parent.get("id")) if parent and parent.get("id") is not None else None,
        "created_at": _optional_str(project.get("createdAt")),
        "updated_at": _optional_str(project.get("updatedAt")),
    }


def parse_attachment(body: dict[str, object]) -> dict[str, object]:
    """Normalize an ``attachment:created`` payload (doc §10b).

    The container is the owning work package, when present.
    """
    attachment = body.get("attachment")
    if not isinstance(attachment, dict):
        return {}
    embedded = _as_dict(attachment.get("_embedded"))
    container = (
        _as_dict(embedded.get("container")) if embedded.get("container") is not None else None
    )
    links = _as_dict(attachment.get("_links"))
    return {
        "external_id": str(attachment.get("id") or ""),
        "file_name": str(attachment.get("fileName") or ""),
        "content_type": str(attachment.get("contentType") or ""),
        "file_size": attachment.get("fileSize"),
        "download_url": _as_dict(links.get("downloadLocation")).get("href"),
        "work_item_id": (
            str(container.get("id"))
            if container
            and container.get("id") is not None
            and container.get("_type") == "WorkPackage"
            else None
        ),
        "created_at": _optional_str(attachment.get("createdAt")),
    }


def diff_snapshots(
    previous: OpenProjectWorkItemSnapshot | None,
    current: OpenProjectWorkItemSnapshot,
) -> list[SemanticChange]:
    """Compare snapshots and emit semantic changes (doc §14).

    When there is no previous snapshot (work item created), the first snapshot
    emits no changes: creation is signaled by the webhook action itself.
    """
    if previous is None:
        return []
    changes: list[SemanticChange] = []
    if previous.summary != current.summary:
        changes.append(SemanticChange.SUMMARY_CHANGED)
    if previous.description != current.description:
        changes.append(SemanticChange.DESCRIPTION_CHANGED)
    if previous.assignee_id != current.assignee_id:
        changes.append(SemanticChange.ASSIGNEE_CHANGED)
    if previous.state != current.state:
        changes.append(SemanticChange.STATE_CHANGED)
    if previous.priority != current.priority:
        changes.append(SemanticChange.PRIORITY_CHANGED)
    if previous.parent_id != current.parent_id:
        changes.append(SemanticChange.PARENT_CHANGED)
    return changes


def event_type_for_action(action: str) -> EventType | None:
    """Map a webhook action to the canonical event type (doc §1)."""
    mapping: dict[str, EventType] = {
        "work_package:created": EventType.WORK_ITEM_CREATED,
        "work_package:updated": EventType.WORK_ITEM_CHANGED,
    }
    return mapping.get(action)


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _normalize_attachments(elements: object) -> list[dict[str, object]]:
    if not isinstance(elements, list):
        return []
    result: list[dict[str, object]] = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        links = _as_dict(item.get("_links"))
        result.append(
            {
                "id": item.get("id"),
                "file_name": item.get("fileName"),
                "content_type": item.get("contentType"),
                "file_size": item.get("fileSize"),
                "download_url": _as_dict(links.get("downloadLocation")).get("href"),
            }
        )
    return result


def _normalize_relations(elements: object) -> list[dict[str, object]]:
    if not isinstance(elements, list):
        return []
    result: list[dict[str, object]] = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": item.get("id"),
                "source_id": item.get("from"),
                "target_id": item.get("to"),
                "relation_type": item.get("type"),
            }
        )
    return result


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "OpenProjectWorkItemSnapshot",
    "SemanticChange",
    "diff_snapshots",
    "event_type_for_action",
    "id_from_href",
    "parse_action",
    "parse_attachment",
    "parse_project",
    "parse_work_item",
]
