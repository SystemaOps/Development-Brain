from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Iterable
from pathlib import Path

from agent_core.domain.repositories import (
    RepositoryBinding,
    UnknownRepositoryError,
    resolve_repository_path,
    resolve_repository_root,
)
from agent_core.ports.repository import RepositoryPort, RepositorySnapshot


class LocalRepositoryFilesystem(RepositoryPort):
    def __init__(self, bindings: Iterable[RepositoryBinding]):
        self._bindings: dict[str, RepositoryBinding] = {}
        for binding in bindings:
            if binding.repository_key in self._bindings:
                raise ValueError(f"Duplicate repository binding: {binding.repository_key}")
            self._bindings[binding.repository_key] = binding

    def resolve_path(self, *, repository_key: str, relative_path: str) -> str:
        binding = self._get_binding(repository_key)
        return str(
            resolve_repository_path(binding, relative_path, for_write=False).absolute_path
        )

    def resolve_write_path(self, *, repository_key: str, relative_path: str) -> str:
        binding = self._get_binding(repository_key)
        return str(
            resolve_repository_path(binding, relative_path, for_write=True).absolute_path
        )

    async def read_text(self, *, repository_key: str, relative_path: str) -> str:
        path = Path(self.resolve_path(repository_key=repository_key, relative_path=relative_path))
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def snapshot(self, *, repository_key: str) -> RepositorySnapshot:
        binding = self._get_binding(repository_key)
        root = resolve_repository_root(binding)
        return await asyncio.to_thread(_git_snapshot, repository_key, root)

    async def diff(self, *, repository_key: str) -> str:
        binding = self._get_binding(repository_key)
        root = resolve_repository_root(binding)
        return await asyncio.to_thread(_git_output, root, ["diff", "--"])

    async def status(self, *, repository_key: str) -> str:
        binding = self._get_binding(repository_key)
        root = resolve_repository_root(binding)
        return await asyncio.to_thread(_git_output, root, ["status", "--porcelain"])

    def _get_binding(self, repository_key: str) -> RepositoryBinding:
        try:
            return self._bindings[repository_key]
        except KeyError as exc:
            raise UnknownRepositoryError(f"Unknown repository: {repository_key}") from exc


def _git_snapshot(repository_key: str, root: Path) -> RepositorySnapshot:
    commit_sha = _git_output(root, ["rev-parse", "HEAD"]).strip() or None
    branch = _git_output(root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip() or None
    status = _git_output(root, ["status", "--porcelain"])
    warning = None
    if commit_sha is None:
        warning = "Repository is not a git working tree or git is unavailable"
    return RepositorySnapshot(
        repository_key=repository_key,
        commit_sha=commit_sha,
        dirty=bool(status.strip()),
        branch=branch,
        status_porcelain=status,
        warning=warning,
    )


def _git_output(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    if result.returncode != 0:
        return ""
    return result.stdout
