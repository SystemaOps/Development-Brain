"""Repository scan persistence contracts."""

from __future__ import annotations

import pytest

from brain.domain.identity import new_repository_id
from brain.domain.repository_scan import (
    RepositoryChangeSet,
    RepositorySnapshot,
    classify_changed_files,
)
from brain.ports.repository_scan import (
    RepositoryChangeSetRepository,
    RepositorySnapshotRepository,
)


class RepositorySnapshotRepositoryContract:
    @pytest.fixture
    def snapshots(self) -> RepositorySnapshotRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, snapshots: RepositorySnapshotRepository) -> None:
        assert isinstance(snapshots, RepositorySnapshotRepository)

    async def test_save_and_get_snapshot(self, snapshots: RepositorySnapshotRepository) -> None:
        repository_id = new_repository_id()
        snapshot = RepositorySnapshot(
            repository_id=repository_id,
            revision="abc123",
            tree=["src/main.py", "README.md"],
            languages=["Python"],
            manifest_files=["pyproject.toml"],
        )
        await snapshots.save_snapshot(snapshot)
        assert await snapshots.get_snapshot(repository_id, "abc123") == snapshot

    async def test_get_missing_revision(self, snapshots: RepositorySnapshotRepository) -> None:
        assert await snapshots.get_snapshot(new_repository_id(), "nope") is None

    async def test_snapshot_per_revision_are_distinct(
        self, snapshots: RepositorySnapshotRepository
    ) -> None:
        repository_id = new_repository_id()
        first = RepositorySnapshot(repository_id=repository_id, revision="rev1", tree=["a.py"])
        second = RepositorySnapshot(
            repository_id=repository_id, revision="rev2", tree=["a.py", "b.py"]
        )
        await snapshots.save_snapshot(first)
        await snapshots.save_snapshot(second)
        assert await snapshots.get_snapshot(repository_id, "rev1") == first
        assert await snapshots.get_snapshot(repository_id, "rev2") == second
        listed = await snapshots.list_snapshots(repository_id)
        assert len(listed) == 2

    async def test_saving_same_revision_upserts(
        self, snapshots: RepositorySnapshotRepository
    ) -> None:
        repository_id = new_repository_id()
        await snapshots.save_snapshot(RepositorySnapshot(repository_id=repository_id, revision="r"))
        updated = RepositorySnapshot(
            repository_id=repository_id, revision="r", languages=["Python"]
        )
        await snapshots.save_snapshot(updated)
        assert await snapshots.get_snapshot(repository_id, "r") == updated
        assert len(await snapshots.list_snapshots(repository_id)) == 1


class RepositoryChangeSetRepositoryContract:
    @pytest.fixture
    def change_sets(self) -> RepositoryChangeSetRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, change_sets: RepositoryChangeSetRepository) -> None:
        assert isinstance(change_sets, RepositoryChangeSetRepository)

    async def test_save_and_list_change_sets(
        self, change_sets: RepositoryChangeSetRepository
    ) -> None:
        repository_id = new_repository_id()
        change_set = RepositoryChangeSet(
            repository_id=repository_id,
            old_revision="old",
            new_revision="new",
            files=classify_changed_files(["src/app.py", "README.md"]),
        )
        await change_sets.save_change_set(change_set)
        listed = await change_sets.list_change_sets(repository_id)
        assert listed == [change_set]

    async def test_change_sets_are_filtered_by_repository(
        self, change_sets: RepositoryChangeSetRepository
    ) -> None:
        other = new_repository_id()
        await change_sets.save_change_set(
            RepositoryChangeSet(repository_id=new_repository_id(), new_revision="r1")
        )
        await change_sets.save_change_set(
            RepositoryChangeSet(repository_id=other, new_revision="r2")
        )
        assert len(await change_sets.list_change_sets(other)) == 1
