"""Local Git adapter.

Implements :class:`~brain.ports.source_control.SourceControlPort` by driving the
``git`` CLI with ``asyncio`` subprocesses, so no Python git binding is required.

Workspace layout under a configurable root directory:

.. code-block:: text

    <workspace_root>/
        <repository.id>/          clone of the repository
        <repository.id>/worktrees/<branch>/   isolated worktrees (execution-9284)

Clone URLs may be local paths or remote URLs; ``git clone`` handles both.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from brain.domain.repositories import Repository


class GitError(RuntimeError):
    """Raised when a git CLI invocation fails."""


def _safe_branch(branch_name: str) -> str:
    """Sanitize a branch name into a filesystem-safe worktree directory name."""
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in branch_name)


class LocalGitAdapter:
    """SourceControlPort backed by the system ``git`` executable."""

    def __init__(self, workspace_root: Path) -> None:
        if shutil.which("git") is None:
            raise RuntimeError("git executable not found on PATH")
        self._workspace_root = workspace_root
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._worktree_paths: dict[tuple[uuid.UUID, str], Path] = {}

    def _clone_dir(self, repository: Repository) -> Path:
        return self._workspace_root / str(repository.id)

    def _worktree_dir(self, repository: Repository, branch_name: str) -> Path:
        return self._clone_dir(repository) / "worktrees" / _safe_branch(branch_name)

    async def _git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
    ) -> bytes:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace').strip()}"
            )
        return stdout

    async def _git_text(self, args: list[str], *, cwd: Path | None = None) -> str:
        return (await self._git(args, cwd=cwd)).decode(errors="replace").strip()

    async def _git_bytes(self, args: list[str], *, cwd: Path | None = None) -> bytes:
        return await self._git(args, cwd=cwd)

    async def register_repository(self, repository: Repository) -> None:
        """Clone the repository into the workspace if not present."""
        clone_dir = self._clone_dir(repository)
        if (clone_dir / ".git").exists() or (clone_dir / ".git").is_file():
            return
        await self._git(["clone", "--", repository.clone_url, str(clone_dir)])

    async def clone_or_fetch(self, repository: Repository) -> None:
        clone_dir = self._clone_dir(repository)
        if (clone_dir / ".git").exists() or (clone_dir / ".git").is_file():
            await self._git(["fetch", "--all", "--prune"], cwd=clone_dir)
            await self._git(["pull", "--ff-only"], cwd=clone_dir)
        else:
            await self.register_repository(repository)

    async def get_default_branch(self, repository: Repository) -> str:
        clone_dir = self._clone_dir(repository)
        try:
            symbolic = await self._git_text(
                ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=clone_dir
            )
            if symbolic:
                return symbolic.split("/", 1)[-1]
        except GitError:
            pass
        return await self._git_text(["rev-parse", "--abbrev-ref", "HEAD"], cwd=clone_dir)

    async def get_current_revision(self, repository: Repository) -> str:
        clone_dir = self._clone_dir(repository)
        return await self._git_text(["rev-parse", "HEAD"], cwd=clone_dir)

    async def list_changed_files(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> list[str]:
        clone_dir = self._clone_dir(repository)
        out = await self._git_text(
            ["diff", "--name-only", base_revision, target_revision], cwd=clone_dir
        )
        return [line for line in out.splitlines() if line]

    async def read_file_at_revision(
        self, repository: Repository, path: str, revision: str
    ) -> bytes:
        clone_dir = self._clone_dir(repository)
        return await self._git_bytes(["show", f"{revision}:{path}"], cwd=clone_dir)

    async def create_branch(
        self, repository: Repository, branch_name: str, base_revision: str
    ) -> None:
        clone_dir = self._clone_dir(repository)
        await self._git(["branch", branch_name, base_revision], cwd=clone_dir)

    async def create_worktree(
        self,
        repository: Repository,
        branch_name: str,
        base_revision: str,
        path: str,
    ) -> None:
        clone_dir = self._clone_dir(repository)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._git(
            ["worktree", "add", "-b", branch_name, str(target), base_revision], cwd=clone_dir
        )
        self._worktree_paths[(repository.id, branch_name)] = target

    async def get_diff(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> str:
        clone_dir = self._clone_dir(repository)
        return await self._git_text(["diff", base_revision, target_revision], cwd=clone_dir)

    async def commit(self, repository: Repository, branch_name: str, message: str) -> str:
        worktree = self._resolve_worktree(repository, branch_name)
        await self._git(["add", "-A"], cwd=worktree)
        await self._git(["commit", "-m", message], cwd=worktree)
        return await self._git_text(["rev-parse", "HEAD"], cwd=worktree)

    async def push(self, repository: Repository, branch_name: str) -> None:
        worktree = self._resolve_worktree(repository, branch_name)
        await self._git(["push", "-u", "origin", branch_name], cwd=worktree)

    def _resolve_worktree(self, repository: Repository, branch_name: str) -> Path:
        tracked = self._worktree_paths.get((repository.id, branch_name))
        if tracked is not None and tracked.exists():
            return tracked
        fallback = self._worktree_dir(repository, branch_name)
        if fallback.exists():
            return fallback
        raise GitError(f"worktree for branch {branch_name!r} not found")


__all__ = ["GitError", "LocalGitAdapter"]
