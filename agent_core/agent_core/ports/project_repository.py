from __future__ import annotations

from typing import Protocol

from agent_core.domain.projects import Project


class ProjectRepositoryPort(Protocol):
    async def get_by_key(self, project_key: str) -> Project | None:
        ...

    async def save(self, project: Project) -> None:
        ...
