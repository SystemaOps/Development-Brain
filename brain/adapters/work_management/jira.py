"""Jira work-management adapter skeleton (Task 14.6).

Implements the same ``WorkManagementPort`` contract as the OpenProject adapter
so the brain core is interchangeable.  Uses the same transport pattern; a fake
Jira API can be injected for tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId, WorkItemId
from brain.domain.work_items import WorkItem
from brain.domain.work_management import FieldMapping, ProviderMappingSpec
from brain.ports.work_management import WorkManagementPort

JIRA_MAPPING = ProviderMappingSpec(
    provider="jira",
    fields=[
        FieldMapping(canonical_field="title", provider_field="summary"),
        FieldMapping(canonical_field="description", provider_field="description"),
        FieldMapping(canonical_field="type", provider_field="issuetype"),
        FieldMapping(canonical_field="human_work_status", provider_field="status"),
    ],
)


class JiraTransport(Protocol):
    """Minimal Jira REST surface used by the adapter."""

    async def get_issue(self, external_id: str) -> dict[str, Any]: ...

    async def list_updated_issues(self, since: datetime) -> list[dict[str, Any]]: ...

    async def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def update_status(self, external_id: str, status: str) -> None: ...

    async def post_comment(self, external_id: str, body: str) -> None: ...

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None: ...


class JiraAdapter(WorkManagementPort):
    """WorkManagementPort implementation for Jira."""

    def __init__(
        self,
        transport: JiraTransport,
        project_id: ProjectId,
        mapping: ProviderMappingSpec = JIRA_MAPPING,
    ) -> None:
        self._transport = transport
        self._project_id = project_id
        self._mapping = mapping

    async def fetch_work_item(self, ref: ExternalReference) -> WorkItem:
        raw = await self._transport.get_issue(ref.external_id)
        return _to_work_item(ref, raw, self._project_id)

    async def list_changed_work_items(self, since: datetime) -> list[WorkItem]:
        raws = await self._transport.list_updated_issues(since)
        return [_to_work_item(_ref_from_raw(r), r, self._project_id) for r in raws]

    async def publish_work_item(self, work_item: WorkItem) -> ExternalReference:
        payload = {
            "summary": work_item.title,
            "description": work_item.description,
            "issuetype": work_item.type.value,
            "status": work_item.human_work_status.value,
        }
        created = await self._transport.create_issue(payload)
        external_id = str(created.get("key") or created.get("id") or "")
        return ExternalReference(provider="jira", external_id=external_id, external_type="issue")

    async def publish_status(self, work_item_id: WorkItemId, status: str) -> None:
        del work_item_id
        await self._transport.update_status(status, status)

    async def post_execution_result(self, work_item_id: WorkItemId, result: str) -> None:
        del work_item_id
        await self._transport.post_comment("", result)

    async def link_pull_request(self, work_item_id: WorkItemId, pr_ref: ExternalReference) -> None:
        del work_item_id
        await self._transport.link_pull_request("", pr_ref.external_id)


def _to_work_item(ref: ExternalReference, raw: dict[str, Any], project_id: ProjectId) -> WorkItem:
    return WorkItem(
        project_id=project_id,
        title=str(raw.get("summary") or raw.get("title") or ref.external_id),
        description=str(raw.get("description") or ""),
        human_work_status=raw.get("status", "new"),
        external_refs=[ref],
    )


def _ref_from_raw(raw: dict[str, Any]) -> ExternalReference:
    return ExternalReference(
        provider="jira",
        external_id=str(raw.get("key") or raw.get("id") or ""),
        external_type="issue",
    )


__all__ = ["JIRA_MAPPING", "JiraAdapter", "JiraTransport"]
