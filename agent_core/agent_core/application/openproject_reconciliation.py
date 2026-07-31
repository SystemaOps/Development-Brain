from __future__ import annotations

from typing import Any


def detect_human_edit_summary(
    *,
    before_payload: dict[str, Any],
    agent_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    edits: list[dict[str, Any]] = []
    for field_name, before_value, agent_value in _comparable_fields(
        before_payload=before_payload,
        agent_payload=agent_payload,
    ):
        if before_value is not None and agent_value is not None and before_value != agent_value:
            edits.append(
                {
                    "field": field_name,
                    "before": before_value,
                    "agent": agent_value,
                }
            )
    return edits


def _comparable_fields(
    *,
    before_payload: dict[str, Any],
    agent_payload: dict[str, Any],
) -> list[tuple[str, Any, Any]]:
    return [
        ("subject", before_payload.get("subject"), agent_payload.get("subject")),
        (
            "description.raw",
            _description_raw(before_payload.get("description")),
            _description_raw(agent_payload.get("description")),
        ),
        (
            "status",
            _link_title(before_payload, "status"),
            _agent_link_title(agent_payload, "status"),
        ),
        (
            "type",
            _link_title(before_payload, "type"),
            _agent_link_title(agent_payload, "type"),
        ),
        (
            "priority",
            _link_title(before_payload, "priority"),
            _agent_link_title(agent_payload, "priority"),
        ),
    ]


def _description_raw(value: Any) -> str | None:
    if isinstance(value, dict):
        raw = value.get("raw")
        return str(raw) if raw is not None else None
    if value is None:
        return None
    return str(value)


def _link_title(payload: dict[str, Any], link_name: str) -> str | None:
    link = payload.get("_links", {}).get(link_name)
    if isinstance(link, dict):
        title = link.get("title")
        return str(title) if title is not None else None
    return None


def _agent_link_title(payload: dict[str, Any], link_name: str) -> str | None:
    return _link_title(payload, link_name)
