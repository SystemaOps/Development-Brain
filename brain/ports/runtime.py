"""Runtime intelligence ports (Phase 19).

``RuntimeEvidenceRepository`` persists observed runtime facts and exposes
queries that answer both "what code may depend on a symbol" (static) and
"what tests/runtime paths actually exercised it" (runtime) — the Phase 19
completion gate.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import ExecutionId, ProjectId, RepositoryId
from brain.domain.runtime import (
    CoverageRecord,
    RuntimeDependency,
    RuntimeObservation,
)


@runtime_checkable
class RuntimeEvidenceRepository(Protocol):
    async def save_observation(self, observation: RuntimeObservation) -> RuntimeObservation: ...

    async def list_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[RuntimeObservation]: ...

    async def list_for_execution(self, execution_id: ExecutionId) -> list[RuntimeObservation]: ...

    async def list_for_project(self, project_id: ProjectId) -> list[RuntimeObservation]: ...

    async def coverage_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[CoverageRecord]: ...

    async def dependencies_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[RuntimeDependency]: ...

    async def observations_for_symbol(
        self, repository_id: RepositoryId, revision: str, symbol: str
    ) -> list[RuntimeObservation]: ...


__all__ = ["RuntimeEvidenceRepository"]
