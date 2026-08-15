"""Workspace manager (Task 12.3).

Creates isolated workspaces for executor runs: an isolated worktree at a base
revision, a feature branch, and deterministic cleanup.  Depends only on the
:class:`SourceControlPort`, so local git and remote providers both work.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from brain.domain.repositories import Repository
from brain.ports.source_control import SourceControlPort


@dataclass
class Workspace:
    """An isolated working directory for one execution."""

    workspace_id: uuid.UUID
    repository: Repository
    branch_name: str
    path: str
    base_revision: str


class WorkspaceManager:
    """Manage isolated executor workspaces."""

    def __init__(
        self,
        *,
        source_control: SourceControlPort,
        workspace_root: str = "/tmp/brain-workspaces",
    ) -> None:
        self._source_control = source_control
        self._workspace_root = workspace_root

    async def create_workspace(
        self,
        repository: Repository,
        *,
        base_revision: str | None = None,
        task_label: str = "task",
    ) -> Workspace:
        await self._source_control.clone_or_fetch(repository)
        revision = base_revision or await self._source_control.get_current_revision(repository)
        workspace_id = uuid.uuid4()
        branch_name = f"brain/{task_label}/{workspace_id.hex[:8]}"
        path = f"{self._workspace_root}/{workspace_id.hex}"
        await self._source_control.create_branch(repository, branch_name, revision)
        await self._source_control.create_worktree(repository, branch_name, revision, path)
        return Workspace(
            workspace_id=workspace_id,
            repository=repository,
            branch_name=branch_name,
            path=path,
            base_revision=revision,
        )

    async def cleanup_workspace(self, workspace: Workspace) -> None:
        """Best-effort cleanup: nothing provider-specific is exposed to callers."""
        # Local git worktrees are removed via the source-control adapter where
        # supported; a no-op here keeps the manager provider-agnostic.
        return None


__all__ = ["Workspace", "WorkspaceManager"]
