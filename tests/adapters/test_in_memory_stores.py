"""Artifact store, checkpoint store, and null catalog in-memory adapter tests."""

from __future__ import annotations

import pytest

from brain.adapters.in_memory.artifact_store import InMemoryArtifactStore
from brain.adapters.in_memory.catalog import NullSoftwareCatalog
from brain.adapters.in_memory.checkpoint_store import InMemoryCheckpointStore
from brain.domain.projects import Project
from brain.ports.artifact_store import ArtifactStore
from brain.ports.checkpoint_store import CheckpointStore
from brain.ports.software_catalog import SoftwareCatalogPort


@pytest.fixture
def artifact_store() -> ArtifactStore:
    return InMemoryArtifactStore()


@pytest.fixture
def checkpoint_store() -> CheckpointStore:
    return InMemoryCheckpointStore()


async def test_artifact_store_round_trip(artifact_store: ArtifactStore) -> None:
    key = await artifact_store.put("reports/coverage.html", b"<html>90%</html>", "text/html")
    assert key == "reports/coverage.html"
    assert await artifact_store.get(key) == b"<html>90%</html>"
    await artifact_store.delete(key)


async def test_artifact_store_get_missing_raises(artifact_store: ArtifactStore) -> None:
    with pytest.raises(KeyError):
        await artifact_store.get("missing")


async def test_checkpoint_store_save_load_delete(checkpoint_store: CheckpointStore) -> None:
    state = {"stage": "BUILD_CONTEXT", "retry_count": 2}
    await checkpoint_store.save("wf/exec-1", state)
    assert await checkpoint_store.load("wf/exec-1") == state

    state["retry_count"] = 3
    assert (await checkpoint_store.load("wf/exec-1"))["retry_count"] == 2

    await checkpoint_store.delete("wf/exec-1")
    assert await checkpoint_store.load("wf/exec-1") is None


async def test_null_catalog_returns_empty() -> None:
    catalog: SoftwareCatalogPort = NullSoftwareCatalog()
    project = Project(name="auth")
    assert await catalog.list_components(project) == []
    assert await catalog.list_interfaces(project) == []
    assert await catalog.list_resources(project) == []
