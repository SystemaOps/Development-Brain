"""In-memory runtime evidence reference implementation (Phase 19)."""

from __future__ import annotations

from collections import defaultdict

from brain.domain.identity import ExecutionId, ProjectId, RepositoryId
from brain.domain.runtime import (
    CoverageRecord,
    RuntimeDependency,
    RuntimeEvidenceKind,
    RuntimeObservation,
)


class InMemoryRuntimeEvidenceRepository:
    """In-memory storage for observed runtime facts."""

    def __init__(self) -> None:
        self._observations: list[RuntimeObservation] = []

    async def save_observation(self, observation: RuntimeObservation) -> RuntimeObservation:
        self._observations.append(observation)
        return observation

    async def list_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[RuntimeObservation]:
        return [
            obs
            for obs in self._observations
            if obs.repository_id == repository_id and obs.revision == revision
        ]

    async def list_for_execution(self, execution_id: ExecutionId) -> list[RuntimeObservation]:
        return [obs for obs in self._observations if obs.execution_id == execution_id]

    async def list_for_project(self, project_id: ProjectId) -> list[RuntimeObservation]:
        return [obs for obs in self._observations if obs.project_id == project_id]

    async def coverage_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[CoverageRecord]:
        grouped: dict[str, list[RuntimeObservation]] = defaultdict(list)
        for obs in self._observations:
            if (
                obs.repository_id == repository_id
                and obs.revision == revision
                and obs.kind == RuntimeEvidenceKind.COVERAGE
            ):
                grouped[obs.source].append(obs)
        records: list[CoverageRecord] = []
        for test_name, observations in grouped.items():
            by_file: dict[str, list[str]] = defaultdict(list)
            test_path = ""
            for obs in observations:
                by_file[obs.target].extend(obs.symbols)
                test_path = str(obs.detail.get("test_path", test_path))
            records.append(
                CoverageRecord(
                    test_name=test_name,
                    test_path=test_path,
                    executed_files=sorted(by_file),
                    executed_symbols={
                        path: sorted(set(symbols)) for path, symbols in by_file.items()
                    },
                )
            )
        return records

    async def dependencies_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[RuntimeDependency]:
        edges: dict[tuple[str, str, str], list[RuntimeObservation]] = defaultdict(list)
        for obs in self._observations:
            if obs.repository_id != repository_id or obs.revision != revision:
                continue
            relation = _relation_for_kind(obs.kind)
            if relation is None or not obs.source or not obs.target:
                continue
            edges[(relation, obs.source, obs.target)].append(obs)
        return [
            RuntimeDependency(
                relation=relation,
                source=source,
                target=target,
                evidence_count=len(observations),
                observations=[obs.id for obs in observations],
            )
            for (relation, source, target), observations in sorted(
                edges.items(), key=lambda item: -len(item[1])
            )
        ]

    async def observations_for_symbol(
        self, repository_id: RepositoryId, revision: str, symbol: str
    ) -> list[RuntimeObservation]:
        return [
            obs
            for obs in self._observations
            if obs.repository_id == repository_id
            and obs.revision == revision
            and symbol in obs.symbols
        ]


def _relation_for_kind(kind: RuntimeEvidenceKind) -> str | None:
    if kind == RuntimeEvidenceKind.SERVICE_CALL:
        return "SERVICE_CALLS"
    if kind == RuntimeEvidenceKind.DATABASE_ACCESS:
        return "QUERY_ACCESSES"
    if kind == RuntimeEvidenceKind.MESSAGE_PUBLISH:
        return "PUBLISHES_TO"
    if kind == RuntimeEvidenceKind.MESSAGE_CONSUME:
        return "CONSUMES_FROM"
    return None
