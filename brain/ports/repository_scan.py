"""Repository scan persistence ports.

Repository snapshots (tree/languages/manifests at one revision) and change
sets (classified changed files between two revisions) are durable artifacts of
Phase 4: they feed document ingestion, topology discovery, and code
intelligence in later phases.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import RepositoryId
from brain.domain.repository_scan import RepositoryChangeSet, RepositorySnapshot


@runtime_checkable
class RepositorySnapshotRepository(Protocol):
    async def save_snapshot(self, snapshot: RepositorySnapshot) -> RepositorySnapshot: ...

    async def get_snapshot(
        self, repository_id: RepositoryId, revision: str
    ) -> RepositorySnapshot | None: ...

    async def list_snapshots(self, repository_id: RepositoryId) -> list[RepositorySnapshot]: ...


@runtime_checkable
class RepositoryChangeSetRepository(Protocol):
    async def save_change_set(self, change_set: RepositoryChangeSet) -> RepositoryChangeSet: ...

    async def list_change_sets(self, repository_id: RepositoryId) -> list[RepositoryChangeSet]: ...
