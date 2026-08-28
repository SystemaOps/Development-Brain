"""ActivityProjectionRepository contract (Phase 27)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.external_reference import ExternalReference
from brain.domain.human_activity import (
    HumanActivityReference,
    ProjectionStatus,
)
from brain.domain.identity import ObservationId
from brain.ports.human_activity import ActivityProjectionRepository


def _reference() -> HumanActivityReference:
    return HumanActivityReference(
        observation_id=ObservationId(uuid.uuid4()),
        provider="openproject",
        target=ExternalReference(provider="openproject", external_id="42"),
        external_activity_id="comment-1",
        status=ProjectionStatus.PUBLISHED,
    )


class ActivityProjectionRepositoryContract:
    @pytest.fixture
    def projections(self) -> ActivityProjectionRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, projections: ActivityProjectionRepository) -> None:
        assert isinstance(projections, ActivityProjectionRepository)

    async def test_save_and_get(self, projections: ActivityProjectionRepository) -> None:
        reference = _reference()
        await projections.save(reference)
        stored = await projections.get(reference.observation_id, "openproject")
        assert stored is not None
        assert stored.external_activity_id == "comment-1"
        assert stored.status == ProjectionStatus.PUBLISHED

    async def test_get_missing_returns_none(
        self, projections: ActivityProjectionRepository
    ) -> None:
        assert await projections.get(ObservationId(uuid.uuid4()), "jira") is None

    async def test_list_failed(self, projections: ActivityProjectionRepository) -> None:
        failed = HumanActivityReference(
            observation_id=ObservationId(uuid.uuid4()),
            provider="jira",
            target=ExternalReference(provider="jira", external_id="X-1"),
            status=ProjectionStatus.FAILED,
            error="boom",
        )
        await projections.save(failed)
        listed = await projections.list_failed()
        assert any(r.id == failed.id for r in listed)
