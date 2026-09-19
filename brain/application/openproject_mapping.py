"""OpenProject -> canonical type/status mapping (Phase 0.8).

Provider type names (``Task``, ``Bug``, ...) and status names (``In
progress``, ``Closed``, ...) map strictly to canonical
:class:`~brain.domain.work_items.WorkItemType` / ``HumanWorkStatus`` values.
Unknown names fall back (type -> task, status -> new); the raw provider names
are preserved on the work item's ``ExternalReference`` so no information is
lost.  Webhooks, bootstrap and pull all use these functions so every ingestion
path produces identical canonical values.
"""

from __future__ import annotations

from brain.domain.common import Priority
from brain.domain.work_items import HumanWorkStatus, WorkItemType

_TYPE_ALIASES: dict[str, WorkItemType] = {
    "epic": WorkItemType.EPIC,
    "feature": WorkItemType.FEATURE,
    "story": WorkItemType.STORY,
    "user story": WorkItemType.STORY,
    "user_story": WorkItemType.STORY,
    "task": WorkItemType.TASK,
    "bug": WorkItemType.BUG,
    "defect": WorkItemType.BUG,
    "investigation": WorkItemType.INVESTIGATION,
    "refactoring": WorkItemType.REFACTORING,
    "verification": WorkItemType.VERIFICATION,
    "documentation": WorkItemType.DOCUMENTATION,
    "operations": WorkItemType.OPERATIONS,
    "milestone": WorkItemType.TASK,
    "phase": WorkItemType.TASK,
}

_STATUS_ALIASES: dict[str, HumanWorkStatus] = {
    "new": HumanWorkStatus.NEW,
    "in specification": HumanWorkStatus.IN_PROGRESS,
    "in progress": HumanWorkStatus.IN_PROGRESS,
    "in development": HumanWorkStatus.IN_PROGRESS,
    "in review": HumanWorkStatus.IN_PROGRESS,
    "in test": HumanWorkStatus.IN_PROGRESS,
    "blocked": HumanWorkStatus.BLOCKED,
    "done": HumanWorkStatus.DONE,
    "closed": HumanWorkStatus.DONE,
    "rejected": HumanWorkStatus.CANCELLED,
    "cancelled": HumanWorkStatus.CANCELLED,
    "canceled": HumanWorkStatus.CANCELLED,
}

_PRIORITY_ALIASES: dict[str, Priority] = {
    "low": Priority.LOW,
    "normal": Priority.MEDIUM,
    "medium": Priority.MEDIUM,
    "high": Priority.HIGH,
    "urgent": Priority.URGENT,
    "immediate": Priority.CRITICAL,
}


def map_work_item_type(raw: str | None) -> WorkItemType:
    """Map an OpenProject type name to a canonical ``WorkItemType``.

    Falls back to ``TASK`` for unknown type names.
    """
    if not raw:
        return WorkItemType.TASK
    return _TYPE_ALIASES.get(raw.strip().lower(), WorkItemType.TASK)


def map_human_work_status(raw: str | None) -> HumanWorkStatus:
    """Map an OpenProject status name to a canonical ``HumanWorkStatus``.

    Falls back to ``NEW`` for unknown status names.
    """
    if not raw:
        return HumanWorkStatus.NEW
    return _STATUS_ALIASES.get(raw.strip().lower(), HumanWorkStatus.NEW)


def map_work_item_type_or_none(raw: str | None) -> WorkItemType | None:
    """Strict mapping; ``None`` for unknown names (callers may decide)."""
    if not raw:
        return None
    return _TYPE_ALIASES.get(raw.strip().lower())


def map_human_work_status_or_none(raw: str | None) -> HumanWorkStatus | None:
    """Strict mapping; ``None`` for unknown names (callers may decide)."""
    if not raw:
        return None
    return _STATUS_ALIASES.get(raw.strip().lower())


def map_priority(raw: str | None) -> Priority | None:
    """Map an OpenProject priority name to a canonical ``Priority``.

    Unknown priority names map to ``None`` (the work item keeps no priority).
    """
    if not raw:
        return None
    return _PRIORITY_ALIASES.get(raw.strip().lower())


__all__ = [
    "map_human_work_status",
    "map_human_work_status_or_none",
    "map_priority",
    "map_work_item_type",
    "map_work_item_type_or_none",
]
