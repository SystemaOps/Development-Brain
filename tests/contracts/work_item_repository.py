"""WorkItemRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.projects import Project
from brain.domain.work_items import WorkItem, WorkItemType
from brain.ports.repositories import WorkItemRepository


class WorkItemRepositoryContract:
    @pytest.fixture
    def work_item_repository(self) -> WorkItemRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, work_item_repository: WorkItemRepository) -> None:
        assert isinstance(work_item_repository, WorkItemRepository)

    async def test_create_and_get_round_trip(
        self, work_item_repository: WorkItemRepository
    ) -> None:
        project = Project(name="auth")
        item = WorkItem(project_id=project.id, title="Implement account locking")
        await work_item_repository.create(item)
        assert await work_item_repository.get(item.id) == item

    async def test_update_persists(self, work_item_repository: WorkItemRepository) -> None:
        project = Project(name="auth")
        item = WorkItem(project_id=project.id, title="t")
        await work_item_repository.create(item)

        item.title = "updated"
        item.type = WorkItemType.BUG
        await work_item_repository.update(item)

        stored = await work_item_repository.get(item.id)
        assert stored.title == "updated"
        assert stored.type == WorkItemType.BUG

    async def test_list_by_project_and_parent(
        self, work_item_repository: WorkItemRepository
    ) -> None:
        project_a = Project(name="a")
        project_b = Project(name="b")
        parent = WorkItem(project_id=project_a.id, title="parent")
        await work_item_repository.create(parent)
        child = WorkItem(project_id=project_a.id, title="child", parent_id=parent.id)
        await work_item_repository.create(child)
        await work_item_repository.create(WorkItem(project_id=project_b.id, title="other"))

        assert len(await work_item_repository.list_by_project(project_a.id)) == 2
        assert len(await work_item_repository.list_by_project(project_b.id)) == 1
        children = await work_item_repository.list_by_work_item(parent.id)
        assert [c.id for c in children] == [child.id]

    async def test_delete(self, work_item_repository: WorkItemRepository) -> None:
        project = Project(name="auth")
        item = WorkItem(project_id=project.id, title="t")
        await work_item_repository.create(item)
        await work_item_repository.delete(item.id)
        assert await work_item_repository.get(item.id) is None

    async def test_distinct_status_tracks_are_preserved(
        self, work_item_repository: WorkItemRepository
    ) -> None:
        project = Project(name="auth")
        item = WorkItem(project_id=project.id, title="t")
        item.human_work_status = "done"
        item.implementation_status = "code_modified"
        item.verification_status = "failed"
        item.pull_request_status = "created"
        await work_item_repository.create(item)
        stored = await work_item_repository.get(item.id)
        assert stored.human_work_status == "done"
        assert stored.implementation_status == "code_modified"
        assert stored.verification_status == "failed"
        assert stored.pull_request_status == "created"
