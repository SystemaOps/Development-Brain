"""WorkManagementPort contract.

Both the OpenProject adapter and the Jira adapter must pass this contract,
proving the brain core is provider-interchangeable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import new_project_id, new_work_item_id
from brain.domain.work_items import WorkItem
from brain.ports.work_management import WorkManagementPort


class WorkManagementPortContract:
    @pytest.fixture
    def work_management(self) -> WorkManagementPort:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, work_management: WorkManagementPort) -> None:
        assert isinstance(work_management, WorkManagementPort)

    async def test_fetch_work_item(self, work_management: WorkManagementPort) -> None:
        ref = ExternalReference(provider="test", external_id="42")
        work_item = await work_management.fetch_work_item(ref)
        assert isinstance(work_item, WorkItem)
        assert work_item.title

    async def test_publish_work_item_returns_ref(self, work_management: WorkManagementPort) -> None:
        work_item = WorkItem(project_id=new_project_id(), title="Implement login")
        ref = await work_management.publish_work_item(work_item)
        assert isinstance(ref, ExternalReference)
        assert ref.external_id

    async def test_list_changed_work_items(self, work_management: WorkManagementPort) -> None:
        since = datetime.now(UTC) - timedelta(hours=24)
        items = await work_management.list_changed_work_items(since)
        assert isinstance(items, list)

    async def test_publish_status_and_post_result(
        self, work_management: WorkManagementPort
    ) -> None:
        work_item_id = new_work_item_id()
        await work_management.publish_status(work_item_id, "in_progress")
        await work_management.post_execution_result(work_item_id, "all tests passed")

    async def test_link_pull_request(self, work_management: WorkManagementPort) -> None:
        work_item_id = new_work_item_id()
        pr_ref = ExternalReference(provider="fake", external_id="PR-1")
        await work_management.link_pull_request(work_item_id, pr_ref)
