"""Observation repository port (Phase 26).

Stores observations independently of any external comment projection.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import (
    ObservationId,
    ProjectId,
    WorkItemId,
)
from brain.domain.observations import Observation


@runtime_checkable
class ObservationRepository(Protocol):
    async def save(self, observation: Observation) -> Observation: ...

    async def get(self, observation_id: ObservationId) -> Observation | None: ...

    async def list_by_project(self, project_id: ProjectId) -> list[Observation]: ...

    async def list_by_work_item(self, work_item_id: WorkItemId) -> list[Observation]: ...

    async def list_recent(self, limit: int = 100) -> list[Observation]: ...

    async def find_by_dedup_key(self, dedup_key: str) -> Observation | None: ...


__all__ = ["ObservationRepository"]
