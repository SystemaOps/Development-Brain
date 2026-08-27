"""In-memory observation repository reference implementation (Phase 26)."""

from __future__ import annotations

from brain.domain.identity import (
    ObservationId,
    ProjectId,
    WorkItemId,
)
from brain.domain.observations import Observation


class InMemoryObservationRepository:
    """In-memory storage for the engineering journal."""

    def __init__(self) -> None:
        self._observations: dict[ObservationId, Observation] = {}

    async def save(self, observation: Observation) -> Observation:
        self._observations[observation.id] = observation
        return observation

    async def get(self, observation_id: ObservationId) -> Observation | None:
        return self._observations.get(observation_id)

    async def list_by_project(self, project_id: ProjectId) -> list[Observation]:
        return [o for o in self._observations.values() if o.project_id == project_id]

    async def list_by_work_item(self, work_item_id: WorkItemId) -> list[Observation]:
        return [o for o in self._observations.values() if o.work_item_id == work_item_id]

    async def list_recent(self, limit: int = 100) -> list[Observation]:
        return list(self._observations.values())[-limit:]

    async def find_by_dedup_key(self, dedup_key: str) -> Observation | None:
        for observation in self._observations.values():
            if observation.dedup_key == dedup_key:
                return observation
        return None
