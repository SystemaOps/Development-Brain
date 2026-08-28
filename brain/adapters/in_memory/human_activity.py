"""In-memory human activity adapters (Phase 27).

- ``NullHumanActivityPort``: safe no-op when no human tool is configured
  (Task 27.2).
- ``InMemoryActivityProjectionRepository``: idempotency tracking (Task 27.3).
"""

from __future__ import annotations

from brain.domain.external_reference import ExternalReference
from brain.domain.human_activity import (
    HumanActivityReference,
    ProjectionStatus,
)
from brain.domain.identity import ObservationId
from brain.domain.observations import Observation


class NullHumanActivityPort:
    """No-op projection: observation remains stored, nothing is published."""

    async def publish_observation(
        self,
        target: ExternalReference,
        observation: Observation,
    ) -> HumanActivityReference:
        del target
        return HumanActivityReference(
            observation_id=observation.id,
            provider="null",
            target=ExternalReference(provider="null", external_id=""),
            status=ProjectionStatus.SKIPPED,
            error="no human activity provider configured",
        )


class InMemoryActivityProjectionRepository:
    """In-memory projection tracking for idempotency."""

    def __init__(self) -> None:
        self._refs: dict[tuple[ObservationId, str], HumanActivityReference] = {}

    async def save(self, reference: HumanActivityReference) -> HumanActivityReference:
        self._refs[(reference.observation_id, reference.provider)] = reference
        return reference

    async def get(
        self, observation_id: ObservationId, provider: str
    ) -> HumanActivityReference | None:
        return self._refs.get((observation_id, provider))

    async def list_failed(self, limit: int = 100) -> list[HumanActivityReference]:
        failed = [ref for ref in self._refs.values() if ref.status == ProjectionStatus.FAILED]
        return failed[-limit:]

    def published_count(self) -> int:
        return sum(1 for ref in self._refs.values() if ref.status == ProjectionStatus.PUBLISHED)


__all__ = ["InMemoryActivityProjectionRepository", "NullHumanActivityPort"]
