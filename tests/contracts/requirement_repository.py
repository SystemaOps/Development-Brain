"""RequirementRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.projects import Project
from brain.domain.requirements import Requirement, RequirementStatus
from brain.ports.repositories import RequirementRepository


class RequirementRepositoryContract:
    @pytest.fixture
    def requirement_repository(self) -> RequirementRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, requirement_repository: RequirementRepository) -> None:
        assert isinstance(requirement_repository, RequirementRepository)

    async def test_create_and_get_round_trip(
        self, requirement_repository: RequirementRepository
    ) -> None:
        project = Project(name="auth")
        req = Requirement(project_id=project.id, key="REQ-AUTH-12", title="Account locking")
        await requirement_repository.create(req)
        assert await requirement_repository.get(req.id) == req

    async def test_update_persists(self, requirement_repository: RequirementRepository) -> None:
        project = Project(name="auth")
        req = Requirement(project_id=project.id, key="REQ-AUTH-12", title="t")
        await requirement_repository.create(req)

        req.status = RequirementStatus.APPROVED
        await requirement_repository.update(req)

        assert (await requirement_repository.get(req.id)).status == RequirementStatus.APPROVED

    async def test_list_by_project_and_parent(
        self, requirement_repository: RequirementRepository
    ) -> None:
        project = Project(name="auth")
        parent = Requirement(project_id=project.id, title="parent")
        await requirement_repository.create(parent)
        child = Requirement(project_id=project.id, title="child", parent_id=parent.id)
        await requirement_repository.create(child)
        other_project = Project(name="billing")
        await requirement_repository.create(Requirement(project_id=other_project.id, title="other"))

        assert len(await requirement_repository.list_by_project(project.id)) == 2
        children = await requirement_repository.list_by_parent(parent.id)
        assert [c.id for c in children] == [child.id]

    async def test_delete(self, requirement_repository: RequirementRepository) -> None:
        project = Project(name="auth")
        req = Requirement(project_id=project.id, title="t")
        await requirement_repository.create(req)
        await requirement_repository.delete(req.id)
        assert await requirement_repository.get(req.id) is None
