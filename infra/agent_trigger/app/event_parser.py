from __future__ import annotations

from typing import Any

from agent_core.application.event_classification import (
    find_comment_id,
    find_first_key,
    find_project_id,
    find_work_package_id,
    infer_event_type,
    normalize_openproject_event as normalize_openproject_event_envelope,
)
from agent_core.domain.events import (
    calculate_event_idempotency_key,
    canonical_json,
)


def normalize_openproject_event(
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, str | None]:
    envelope = normalize_openproject_event_envelope(payload, headers)
    return {
        "source_tool": envelope.source,
        "event_type": envelope.event_type,
        "external_project_id": envelope.external_project_id,
        "external_work_package_id": envelope.external_work_package_id,
        "external_comment_id": envelope.external_comment_id,
        "idempotency_key": envelope.idempotency_key,
    }


__all__ = [
    "calculate_event_idempotency_key",
    "canonical_json",
    "find_comment_id",
    "find_first_key",
    "find_project_id",
    "find_work_package_id",
    "infer_event_type",
    "normalize_openproject_event",
]
