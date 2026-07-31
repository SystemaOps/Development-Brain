from __future__ import annotations

import re
from typing import Any

from agent_core.domain.events import EventEnvelope

WORK_PACKAGE_HREF_RE = re.compile(r"/api/v3/work_packages/(\d+)")
PROJECT_HREF_RE = re.compile(r"/api/v3/projects/(\d+)")


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def find_first_key(payload: dict[str, Any], names: set[str]) -> str | None:
    for obj in _walk(payload):
        for key, value in obj.items():
            if key in names and value is not None:
                return str(value)
    return None


def find_work_package_id(payload: dict[str, Any]) -> str | None:
    direct = find_first_key(payload, {"work_package_id", "workPackageId", "workPackageID"})
    if direct and direct.isdigit():
        return direct

    for obj in _walk(payload):
        if "workPackage" in obj and isinstance(obj["workPackage"], dict):
            wp_id = obj["workPackage"].get("id")
            if wp_id:
                return str(wp_id)

        if "_links" in obj and isinstance(obj["_links"], dict):
            for link in obj["_links"].values():
                if isinstance(link, dict):
                    href = link.get("href")
                    if isinstance(href, str):
                        match = WORK_PACKAGE_HREF_RE.search(href)
                        if match:
                            return match.group(1)

        for value in obj.values():
            if isinstance(value, str):
                match = WORK_PACKAGE_HREF_RE.search(value)
                if match:
                    return match.group(1)

    return None


def find_project_id(payload: dict[str, Any]) -> str | None:
    direct = find_first_key(payload, {"project_id", "projectId", "projectID"})
    if direct:
        return direct

    for obj in _walk(payload):
        if "project" in obj and isinstance(obj["project"], dict):
            project_id = obj["project"].get("id")
            if project_id:
                return str(project_id)

        for value in obj.values():
            if isinstance(value, str):
                match = PROJECT_HREF_RE.search(value)
                if match:
                    return match.group(1)

    return None


def find_comment_id(payload: dict[str, Any]) -> str | None:
    direct = find_first_key(payload, {"comment_id", "commentId", "activity_id", "activityId"})
    if direct:
        return direct

    for obj in _walk(payload):
        if obj.get("_type") == "Activity::Comment" and obj.get("id"):
            return str(obj["id"])

    return None


def infer_event_type(payload: dict[str, Any], headers: dict[str, str]) -> str:
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    for header_name in ("x-op-event", "x-openproject-event", "x-event-name", "x-webhook-event"):
        if normalized_headers.get(header_name):
            return normalized_headers[header_name]

    for key in ("event_name", "event", "action", "type"):
        value = payload.get(key)
        if value:
            return str(value)

    return "unknown"


def normalize_openproject_event(
    payload: dict[str, Any],
    headers: dict[str, str],
) -> EventEnvelope:
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    return EventEnvelope(
        source="openproject",
        event_type=infer_event_type(payload, normalized_headers),
        external_project_id=find_project_id(payload),
        external_work_package_id=find_work_package_id(payload),
        external_comment_id=find_comment_id(payload),
        headers=normalized_headers,
        payload=payload,
    )
