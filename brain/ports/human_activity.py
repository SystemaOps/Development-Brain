"""Human activity ports (Phase 27).

``HumanActivityPort`` lets the Brain publish selected observations into
whichever human tool is configured; ``ActivityProjectionRepository`` tracks
publications for idempotency.  Workflow nodes never call Jira/OpenProject
directly — they go through these ports.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.external_reference import ExternalReference
from brain.domain.human_activity import HumanActivityReference
from brain.domain.identity import ObservationId
from brain.domain.observations import Observation


@runtime_checkable
class HumanActivityPort(Protocol):
    async def publish_observation(
        self,
        target: ExternalReference,
        observation: Observation,
    ) -> HumanActivityReference: ...


@runtime_checkable
class ActivityProjectionRepository(Protocol):
    async def save(self, reference: HumanActivityReference) -> HumanActivityReference: ...

    async def get(
        self, observation_id: ObservationId, provider: str
    ) -> HumanActivityReference | None: ...

    async def list_failed(self, limit: int = 100) -> list[HumanActivityReference]: ...


__all__ = ["ActivityProjectionRepository", "HumanActivityPort"]
