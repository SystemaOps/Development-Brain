"""Concurrency controls for automated changes (Task 40.6).

Prevents conflicting automated changes to the same repository/worktree/
branch: one execution may hold the lock for a repository at a time.  A
conflicting attempt is marked BLOCKED instead of racing the other execution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from brain.domain.identity import RepositoryId


@dataclass
class WorkspaceLock:
    repository_id: RepositoryId
    owner_execution_id: uuid.UUID
    branch_name: str
    acquired_at: datetime


class WorkspaceLockStore(Protocol):
    async def acquire(self, lock: WorkspaceLock) -> bool:
        """Atomically acquire the lock; False when already held."""
        ...

    async def release(self, repository_id: RepositoryId, owner_execution_id: uuid.UUID) -> bool:
        """Release the lock if held by the given execution."""
        ...

    async def held_by(self, repository_id: RepositoryId) -> WorkspaceLock | None: ...


class InMemoryWorkspaceLockStore:
    """Single-process reference implementation."""

    def __init__(self) -> None:
        self._locks: dict[RepositoryId, WorkspaceLock] = {}

    async def acquire(self, lock: WorkspaceLock) -> bool:
        if lock.repository_id in self._locks:
            return False
        self._locks[lock.repository_id] = lock
        return True

    async def release(self, repository_id: RepositoryId, owner_execution_id: uuid.UUID) -> bool:
        held = self._locks.get(repository_id)
        if held is None or held.owner_execution_id != owner_execution_id:
            return False
        del self._locks[repository_id]
        return True

    async def held_by(self, repository_id: RepositoryId) -> WorkspaceLock | None:
        return self._locks.get(repository_id)


class WorkspaceLockManager:
    """Acquire/release per-repository execution locks."""

    def __init__(self, store: WorkspaceLockStore) -> None:
        self._store = store

    async def try_acquire(
        self,
        repository_id: RepositoryId,
        execution_id: uuid.UUID,
        branch_name: str,
    ) -> WorkspaceLock | None:
        lock = WorkspaceLock(
            repository_id=repository_id,
            owner_execution_id=execution_id,
            branch_name=branch_name,
            acquired_at=datetime.now(UTC),
        )
        if await self._store.acquire(lock):
            return lock
        return None

    async def release(self, repository_id: RepositoryId, execution_id: uuid.UUID) -> bool:
        return await self._store.release(repository_id, execution_id)

    async def held_by(self, repository_id: RepositoryId) -> WorkspaceLock | None:
        return await self._store.held_by(repository_id)


__all__ = ["InMemoryWorkspaceLockStore", "WorkspaceLock", "WorkspaceLockManager"]
