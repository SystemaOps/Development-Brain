"""Source control port (local Git, GitLab, GitHub, ...).

PR/MR operations stay in ``PullRequestPort``; this port owns repository
cloning, revision handling, and workspace operations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.repositories import Repository


@runtime_checkable
class SourceControlPort(Protocol):
    async def register_repository(self, repository: Repository) -> None: ...

    async def clone_or_fetch(self, repository: Repository) -> None: ...

    async def get_default_branch(self, repository: Repository) -> str: ...

    async def get_current_revision(self, repository: Repository) -> str: ...

    async def list_changed_files(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> list[str]: ...

    async def read_file_at_revision(
        self, repository: Repository, path: str, revision: str
    ) -> bytes: ...

    async def create_branch(
        self, repository: Repository, branch_name: str, base_revision: str
    ) -> None: ...

    async def create_worktree(
        self,
        repository: Repository,
        branch_name: str,
        base_revision: str,
        path: str,
    ) -> None: ...

    async def get_diff(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> str: ...

    async def commit(self, repository: Repository, branch_name: str, message: str) -> str: ...

    async def push(self, repository: Repository, branch_name: str) -> None: ...
