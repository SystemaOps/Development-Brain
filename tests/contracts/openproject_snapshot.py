"""OpenProjectSnapshotStore contract (Phase 0.5)."""

from __future__ import annotations

import pytest

from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.ports.openproject_snapshot import OpenProjectSnapshotStore


def _snapshot() -> OpenProjectWorkItemSnapshot:
    return OpenProjectWorkItemSnapshot(
        external_id="43",
        summary="test",
        state="In progress",
        assignee_id="6",
        attachments=[{"id": 3, "file_name": "a.txt"}],
        relations=[{"id": 5, "from": 1, "to": 2, "type": "blocks"}],
    )


class OpenProjectSnapshotStoreContract:
    @pytest.fixture
    def snapshots(self) -> OpenProjectSnapshotStore:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, snapshots: OpenProjectSnapshotStore) -> None:
        assert isinstance(snapshots, OpenProjectSnapshotStore)

    async def test_save_and_get_round_trip(self, snapshots: OpenProjectSnapshotStore) -> None:
        snapshot = _snapshot()
        await snapshots.save(snapshot)
        loaded = await snapshots.get("43")
        assert loaded is not None
        assert loaded.summary == "test"
        assert loaded.assignee_id == "6"
        assert loaded.attachments == [{"id": 3, "file_name": "a.txt"}]
        assert loaded.relations == [{"id": 5, "from": 1, "to": 2, "type": "blocks"}]

    async def test_get_missing_returns_none(self, snapshots: OpenProjectSnapshotStore) -> None:
        assert await snapshots.get("nope") is None

    async def test_save_overwrites(self, snapshots: OpenProjectSnapshotStore) -> None:
        await snapshots.save(_snapshot())
        from dataclasses import replace

        updated = replace(_snapshot(), summary="changed")
        await snapshots.save(updated)
        loaded = await snapshots.get("43")
        assert loaded is not None
        assert loaded.summary == "changed"
