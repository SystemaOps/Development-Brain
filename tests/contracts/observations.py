"""ObservationRepository contract (Phase 26)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import ObservationId, ProjectId, WorkItemId
from brain.domain.observations import (
    Observation,
    ObservationSeverity,
    ObservationStatus,
    ObservationType,
    ObservationVisibility,
)
from brain.ports.observations import ObservationRepository


def _observation() -> Observation:
    return Observation(
        project_id=ProjectId(uuid.uuid4()),
        work_item_id=WorkItemId(uuid.uuid4()),
        observation_type=ObservationType.VERIFICATION_FAILURE,
        severity=ObservationSeverity.ERROR,
        visibility=ObservationVisibility.IMPORTANT,
        title="Verification failed",
        body="acceptance criterion not met",
        dedup_key="verify-abc123",
    )


class ObservationRepositoryContract:
    @pytest.fixture
    def observations(self) -> ObservationRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, observations: ObservationRepository) -> None:
        assert isinstance(observations, ObservationRepository)

    async def test_save_and_get_round_trip(self, observations: ObservationRepository) -> None:
        observation = _observation()
        await observations.save(observation)
        stored = await observations.get(observation.id)
        assert stored is not None
        assert stored.id == observation.id
        assert stored.observation_type == ObservationType.VERIFICATION_FAILURE
        assert stored.visibility == ObservationVisibility.IMPORTANT
        assert stored.status == ObservationStatus.OPEN

    async def test_get_missing_returns_none(self, observations: ObservationRepository) -> None:
        assert await observations.get(ObservationId(uuid.uuid4())) is None

    async def test_list_by_project(self, observations: ObservationRepository) -> None:
        observation = _observation()
        await observations.save(observation)
        listed = await observations.list_by_project(observation.project_id)
        assert [o.id for o in listed] == [observation.id]

    async def test_list_by_work_item(self, observations: ObservationRepository) -> None:
        observation = _observation()
        await observations.save(observation)
        assert observation.work_item_id is not None
        listed = await observations.list_by_work_item(observation.work_item_id)
        assert [o.id for o in listed] == [observation.id]

    async def test_list_recent(self, observations: ObservationRepository) -> None:
        observation = _observation()
        await observations.save(observation)
        recent = await observations.list_recent(limit=10)
        assert any(o.id == observation.id for o in recent)

    async def test_find_by_dedup_key(self, observations: ObservationRepository) -> None:
        observation = _observation()
        await observations.save(observation)
        found = await observations.find_by_dedup_key("verify-abc123")
        assert found is not None
        assert found.id == observation.id

    async def test_find_by_dedup_key_missing(self, observations: ObservationRepository) -> None:
        assert await observations.find_by_dedup_key("nope") is None
