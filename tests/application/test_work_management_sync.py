"""Unit tests for the Phase 14 work-management sync service."""

from __future__ import annotations

from datetime import datetime

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.work_management import (
    InMemoryWorkManagementIntegrationRepository,
)
from brain.adapters.work_management.jira import JiraAdapter
from brain.adapters.work_management.openproject import OpenProjectAdapter
from brain.application.work_management_sync import WorkManagementSyncService
from brain.domain.identity import new_project_id, new_work_item_id
from brain.domain.work_items import WorkItem
from brain.domain.work_management import SyncState


class _FakeOpenProject:
    def __init__(self) -> None:
        self.comments: list[str] = []
        self.statuses: list[str] = []

    async def get_work_package(self, external_id: str) -> dict:
        return {"id": external_id, "subject": f"WP {external_id}", "status": "done"}

    async def list_updated_work_packages(self, since: datetime) -> list[dict]:
        return []

    async def create_work_package(self, payload: dict) -> dict:
        return {"id": "99", "subject": payload.get("subject", "")}

    async def update_status(self, external_id: str, status: str) -> None:
        self.statuses.append(status)

    async def post_comment(self, external_id: str, body: str) -> None:
        self.comments.append(body)

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:
        return None


class _FakeJira:
    async def get_issue(self, external_id: str) -> dict:
        return {"key": external_id, "summary": f"Issue {external_id}", "status": "done"}

    async def list_updated_issues(self, since: datetime) -> list[dict]:
        return []

    async def create_issue(self, payload: dict) -> dict:
        return {"key": "A-99", "summary": payload.get("summary", "")}

    async def update_status(self, external_id: str, status: str) -> None:
        return None

    async def post_comment(self, external_id: str, body: str) -> None:
        return None

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:
        return None


def _openproject_service() -> tuple[WorkManagementSyncService, _FakeOpenProject]:
    transport = _FakeOpenProject()
    provider = OpenProjectAdapter(transport=transport, project_id=new_project_id())
    service = WorkManagementSyncService(
        provider=provider,
        integrations=InMemoryWorkManagementIntegrationRepository(),
        event_bus=InMemoryEventBus(),
    )
    return service, transport


def _jira_service() -> tuple[WorkManagementSyncService, _FakeJira]:
    transport = _FakeJira()
    provider = JiraAdapter(transport=transport, project_id=new_project_id())
    service = WorkManagementSyncService(
        provider=provider,
        integrations=InMemoryWorkManagementIntegrationRepository(),
        event_bus=InMemoryEventBus(),
    )
    return service, transport


async def test_normalize_webhook_openproject() -> None:
    service, _ = _openproject_service()
    result = await service.normalize_webhook("42", {"subject": "Changed"})
    assert result.work_item.title == "WP 42"
    assert result.changed is True


async def test_sync_detects_conflict_openproject() -> None:
    service, _ = _openproject_service()
    work_item_id = new_work_item_id()
    result = await service.sync_from_provider(work_item_id, "42")
    assert result.mappings
    assert result.mappings[0].sync_state == SyncState.SYNCED
    assert result.conflicts  # provider says done, brain says verification_pending


async def test_publish_work_item_creates_mapping() -> None:
    service, _ = _openproject_service()
    work_item = WorkItem(project_id=new_project_id(), title="Implement login")
    mapping = await service.publish_work_item(work_item)
    assert mapping.external_id == "99"
    assert mapping.sync_state == SyncState.SYNCED


async def test_jira_interchangeable() -> None:
    service, _ = _jira_service()
    work_item = WorkItem(project_id=new_project_id(), title="Implement login")
    mapping = await service.publish_work_item(work_item)
    assert mapping.external_id == "A-99"
    result = await service.sync_from_provider(new_work_item_id(), "A-1")
    assert result.mappings


async def test_post_execution_result_openproject() -> None:
    service, transport = _openproject_service()
    await service._provider.post_execution_result(new_work_item_id(), "tests passed")
    assert transport.comments == ["tests passed"]
