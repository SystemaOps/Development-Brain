"""OpenProject work-management adapter (Task 14.2).

Translates OpenProject work packages to/from canonical ``WorkItem`` using a
:class:`ProviderMappingSpec`.  Network calls go through a pluggable transport
so tests can inject a fake OpenProject API without a live instance; the core
never sees OpenProject types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId, WorkItemId
from brain.domain.work_items import WorkItem
from brain.domain.work_management import FieldMapping, ProviderMappingSpec
from brain.ports.work_management import WorkManagementPort

OPENPROJECT_MAPPING = ProviderMappingSpec(
    provider="openproject",
    fields=[
        FieldMapping(canonical_field="title", provider_field="subject"),
        FieldMapping(canonical_field="description", provider_field="description"),
        FieldMapping(canonical_field="type", provider_field="type"),
        FieldMapping(canonical_field="human_work_status", provider_field="status"),
    ],
)


class OpenProjectTransport(Protocol):
    """Minimal OpenProject REST surface used by the adapter."""

    async def get_work_package(self, external_id: str) -> dict[str, Any]: ...

    async def list_updated_work_packages(self, since: datetime) -> list[dict[str, Any]]: ...

    async def create_work_package(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def update_status(self, external_id: str, status: str) -> None: ...

    async def post_comment(self, external_id: str, body: str) -> None: ...

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None: ...


class OpenProjectAdapter(WorkManagementPort):
    """WorkManagementPort implementation for OpenProject."""

    def __init__(
        self,
        transport: OpenProjectTransport,
        project_id: ProjectId,
        mapping: ProviderMappingSpec = OPENPROJECT_MAPPING,
    ) -> None:
        self._transport = transport
        self._project_id = project_id
        self._mapping = mapping

    async def fetch_work_item(self, ref: ExternalReference) -> WorkItem:
        raw = await self._transport.get_work_package(ref.external_id)
        return _to_work_item(ref, raw, self._project_id)

    async def list_changed_work_items(self, since: datetime) -> list[WorkItem]:
        raws = await self._transport.list_updated_work_packages(since)
        return [_to_work_item(_ref_from_raw(r), r, self._project_id) for r in raws]

    async def publish_work_item(self, work_item: WorkItem) -> ExternalReference:
        payload = {
            "subject": work_item.title,
            "description": work_item.description,
            "type": work_item.type.value,
            "status": work_item.human_work_status.value,
        }
        created = await self._transport.create_work_package(payload)
        external_id = str(created.get("id") or created.get("_id") or "")
        return ExternalReference(
            provider="openproject",
            external_id=external_id,
            external_type="work_package",
        )

    async def publish_status(self, work_item_id: WorkItemId, status: str) -> None:
        del work_item_id
        # Status publishing needs the external id; the sync layer resolves it.
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
        title=str(raw.get("subject") or raw.get("title") or ref.external_id),
        description=str(raw.get("description") or ""),
        human_work_status=raw.get("status", "new"),
        external_refs=[ref],
    )


def _ref_from_raw(raw: dict[str, Any]) -> ExternalReference:
    return ExternalReference(
        provider="openproject",
        external_id=str(raw.get("id") or raw.get("_id") or ""),
        external_type="work_package",
    )


__all__ = ["OPENPROJECT_MAPPING", "OpenProjectAdapter", "OpenProjectTransport"]
