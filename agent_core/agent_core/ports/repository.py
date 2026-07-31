from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agent_core.domain.repositories import RepositoryBinding


@dataclass(frozen=True)
class RepositorySnapshot:
    repository_key: str
    commit_sha: str | None
    dirty: bool
    branch: str | None = None
    status_porcelain: str = ""
    warning: str | None = None


class RepositoryPort(Protocol):
    def resolve_path(self, *, repository_key: str, relative_path: str) -> str:
        ...

    def resolve_write_path(self, *, repository_key: str, relative_path: str) -> str:
        ...

    async def read_text(self, *, repository_key: str, relative_path: str) -> str:
        ...

    async def snapshot(self, *, repository_key: str) -> RepositorySnapshot:
        ...

    async def diff(self, *, repository_key: str) -> str:
        ...

    async def status(self, *, repository_key: str) -> str:
        ...


class RepositoryBindingStorePort(Protocol):
    async def upsert_binding(
        self,
        *,
        project_id: UUID,
        binding: RepositoryBinding,
    ) -> RepositoryBinding:
        ...

    async def get_binding(
        self,
        *,
        project_id: UUID,
        repository_key: str,
    ) -> RepositoryBinding | None:
        ...
