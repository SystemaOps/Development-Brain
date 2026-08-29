"""ProjectRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.projects import Project, ProjectStatus
from brain.ports.repositories import ProjectRepository


class ProjectRepositoryContract:
    @pytest.fixture
    def project_repository(self) -> ProjectRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, project_repository: ProjectRepository) -> None:
        assert isinstance(project_repository, ProjectRepository)

    async def test_create_and_get_round_trip(self, project_repository: ProjectRepository) -> None:
        project = Project(name="auth")
        await project_repository.create(project)
        assert await project_repository.get(project.id) == project

    async def test_get_missing_returns_none(self, project_repository: ProjectRepository) -> None:
        assert await project_repository.get(Project(name="x").id) is None

    async def test_list_and_update(self, project_repository: ProjectRepository) -> None:
        first = Project(name="first")
        second = Project(name="second")
        await project_repository.create(first)
        await project_repository.create(second)

        first.status = ProjectStatus.ACTIVE
        await project_repository.update(first)

        names = sorted(p.name for p in await project_repository.list())
        assert names == ["first", "second"]
        assert (await project_repository.get(first.id)).status == ProjectStatus.ACTIVE

    async def test_delete(self, project_repository: ProjectRepository) -> None:
        project = Project(name="temp")
        await project_repository.create(project)
        await project_repository.delete(project.id)
        assert await project_repository.get(project.id) is None

    async def test_multiple_projects_keep_distinct_ids(
        self, project_repository: ProjectRepository
    ) -> None:
        first = Project(name="a")
        second = Project(name="b")
        await project_repository.create(first)
        await project_repository.create(second)
        assert first.id != second.id
        assert await project_repository.get(first.id) == first
        assert await project_repository.get(second.id) == second
