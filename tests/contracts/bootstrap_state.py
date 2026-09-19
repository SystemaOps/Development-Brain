"""BootstrapStateRepository contract (Phase 0.7)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.bootstrap_state import (
    BootstrapStage,
    BootstrapStatus,
    ProviderBootstrapState,
)
from brain.domain.identity import ProjectId
from brain.ports.bootstrap_state import BootstrapStateRepository


class BootstrapStateRepositoryContract:
    @pytest.fixture
    def bootstrap_states(self) -> BootstrapStateRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, bootstrap_states: BootstrapStateRepository) -> None:
        assert isinstance(bootstrap_states, BootstrapStateRepository)

    async def test_save_and_get(self, bootstrap_states: BootstrapStateRepository) -> None:
        project_id = ProjectId(uuid.uuid4())
        state = ProviderBootstrapState(
            project_id=project_id,
            provider="openproject",
            status=BootstrapStatus.INGESTING,
            stage=BootstrapStage.FETCH_WORK_ITEMS,
            last_page=3,
            items_processed=75,
        )
        await bootstrap_states.save(state)
        loaded = await bootstrap_states.get(project_id, "openproject")
        assert loaded is not None
        assert loaded.status == BootstrapStatus.INGESTING
        assert loaded.stage == BootstrapStage.FETCH_WORK_ITEMS
        assert loaded.last_page == 3
        assert loaded.items_processed == 75

    async def test_get_missing_returns_none(
        self, bootstrap_states: BootstrapStateRepository
    ) -> None:
        assert await bootstrap_states.get(ProjectId(uuid.uuid4()), "openproject") is None

    async def test_save_updates_in_place(self, bootstrap_states: BootstrapStateRepository) -> None:
        project_id = ProjectId(uuid.uuid4())
        state = ProviderBootstrapState(project_id=project_id, provider="openproject")
        await bootstrap_states.save(state)
        state = state.model_copy(update={"status": BootstrapStatus.READY})
        await bootstrap_states.save(state)
        loaded = await bootstrap_states.get(project_id, "openproject")
        assert loaded is not None
        assert loaded.status == BootstrapStatus.READY
