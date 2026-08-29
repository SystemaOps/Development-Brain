"""WorkManagementIntegrationRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.identity import new_work_item_id
from brain.domain.work_management import (
    IntegrationMapping,
    SyncConflict,
    SyncState,
)
from brain.ports.work_management_repo import WorkManagementIntegrationRepository


class WorkManagementIntegrationRepositoryContract:
    @pytest.fixture
    def work_management_integrations(self) -> WorkManagementIntegrationRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(
        self, work_management_integrations: WorkManagementIntegrationRepository
    ) -> None:
        assert isinstance(work_management_integrations, WorkManagementIntegrationRepository)

    async def test_mapping_round_trip(
        self, work_management_integrations: WorkManagementIntegrationRepository
    ) -> None:
        work_item_id = new_work_item_id()
        mapping = IntegrationMapping(
            work_item_id=work_item_id,
            provider="openproject",
            external_id="42",
            sync_state=SyncState.SYNCED,
        )
        await work_management_integrations.save_mapping(mapping)
        stored = await work_management_integrations.get_mapping(work_item_id, "openproject")
        assert stored is not None
        assert stored.external_id == "42"
        assert stored.sync_state == SyncState.SYNCED

    async def test_list_mappings_by_work_item(
        self, work_management_integrations: WorkManagementIntegrationRepository
    ) -> None:
        work_item_id = new_work_item_id()
        await work_management_integrations.save_mapping(
            IntegrationMapping(work_item_id=work_item_id, provider="openproject", external_id="1")
        )
        await work_management_integrations.save_mapping(
            IntegrationMapping(work_item_id=work_item_id, provider="jira", external_id="A-1")
        )
        mappings = await work_management_integrations.list_mappings(work_item_id)
        assert len(mappings) == 2

    async def test_conflict_round_trip(
        self, work_management_integrations: WorkManagementIntegrationRepository
    ) -> None:
        work_item_id = new_work_item_id()
        conflict = SyncConflict(
            work_item_id=work_item_id,
            provider="openproject",
            external_id="42",
            provider_field="status",
            provider_value="done",
            brain_value="verification_failed",
        )
        await work_management_integrations.save_conflict(conflict)
        conflicts = await work_management_integrations.list_conflicts(work_item_id)
        assert len(conflicts) == 1
        assert conflicts[0].provider_value == "done"
        assert conflicts[0].brain_value == "verification_failed"
