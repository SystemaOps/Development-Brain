"""Observation projection service (Phase 27).

Projects selected observations into the configured human tool through
``HumanActivityPort``, tracking publications so retries never create duplicate
human comments (Task 27.3).  With no human tool configured the projection
safely no-ops via the null adapter and the observation stays stored
(Task 27.2).
"""

from __future__ import annotations

import logging

from brain.domain.external_reference import ExternalReference
from brain.domain.human_activity import (
    HumanActivityReference,
    ProjectionStatus,
)
from brain.domain.observations import Observation
from brain.ports.human_activity import (
    ActivityProjectionRepository,
    HumanActivityPort,
)
from brain.ports.observations import ObservationRepository

logger = logging.getLogger(__name__)


class ObservationProjectionService:
    """Publishes observations to human tools with idempotent tracking."""

    def __init__(
        self,
        *,
        projections: ActivityProjectionRepository,
        port: HumanActivityPort,
        observations: ObservationRepository,
    ) -> None:
        self._projections = projections
        self._port = port
        self._observations = observations

    async def project(
        self,
        observation: Observation,
        target: ExternalReference,
        *,
        force: bool = False,
    ) -> HumanActivityReference:
        """Publish one observation to one human tool, idempotently.

        A prior successful publication for the same observation+provider is
        reused (no duplicate comment).  ``force=True`` re-publishes.
        """
        existing = await self._projections.get(observation.id, target.provider)
        if existing is not None and existing.status == ProjectionStatus.PUBLISHED and not force:
            return existing

        reference = await self._port.publish_observation(target, observation)
        await self._projections.save(reference)
        if reference.status == ProjectionStatus.PUBLISHED:
            logger.info(
                "observation %s projected to %s (%s)",
                observation.id,
                target.provider,
                reference.external_activity_id,
            )
        else:
            logger.warning(
                "observation %s projection to %s failed: %s",
                observation.id,
                target.provider,
                reference.error,
            )
        return reference

    async def retry_failed(self, limit: int = 100) -> list[HumanActivityReference]:
        """Re-project previously failed publications idempotently (Task 29.7)."""
        retried: list[HumanActivityReference] = []
        for reference in await self._projections.list_failed(limit=limit):
            if reference.status != ProjectionStatus.FAILED:
                continue
            observation = await self._observations.get(reference.observation_id)
            if observation is None:
                continue
            updated = await self.project(
                observation,
                reference.target,
                force=True,
            )
            if updated.status == ProjectionStatus.PUBLISHED:
                retried.append(updated)
        return retried


__all__ = ["ObservationProjectionService"]
