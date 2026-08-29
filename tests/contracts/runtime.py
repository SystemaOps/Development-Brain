"""RuntimeEvidenceRepository contract (Phase 19)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import ExecutionId, ProjectId, RepositoryId
from brain.domain.runtime import (
    RuntimeEvidenceKind,
    RuntimeObservation,
)
from brain.ports.runtime import RuntimeEvidenceRepository

_REPOSITORY_ID = RepositoryId(uuid.uuid4())
_REVISION = "abc123"


def _coverage(test: str, path: str, symbols: list[str]) -> RuntimeObservation:
    return RuntimeObservation(
        kind=RuntimeEvidenceKind.COVERAGE,
        repository_id=_REPOSITORY_ID,
        revision=_REVISION,
        source=test,
        target=path,
        symbols=symbols,
        detail={"test_path": f"tests/{test}.py"},
    )


def _service_call(source: str, target: str) -> RuntimeObservation:
    return RuntimeObservation(
        kind=RuntimeEvidenceKind.SERVICE_CALL,
        repository_id=_REPOSITORY_ID,
        revision=_REVISION,
        source=source,
        target=target,
    )


class RuntimeEvidenceRepositoryContract:
    @pytest.fixture
    def runtime(self) -> RuntimeEvidenceRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, runtime: RuntimeEvidenceRepository) -> None:
        assert isinstance(runtime, RuntimeEvidenceRepository)

    async def test_save_and_list_for_revision(self, runtime: RuntimeEvidenceRepository) -> None:
        obs = _coverage("test_auth", "services/auth.py", ["auth.login"])
        await runtime.save_observation(obs)
        listed = await runtime.list_for_revision(_REPOSITORY_ID, _REVISION)
        assert [o.id for o in listed] == [obs.id]

    async def test_list_for_revision_filters_by_revision(
        self, runtime: RuntimeEvidenceRepository
    ) -> None:
        await runtime.save_observation(_coverage("test_auth", "services/auth.py", ["auth.login"]))
        assert await runtime.list_for_revision(_REPOSITORY_ID, "other-rev") == []

    async def test_list_for_execution(self, runtime: RuntimeEvidenceRepository) -> None:
        execution_id = ExecutionId(uuid.uuid4())
        obs = RuntimeObservation(
            kind=RuntimeEvidenceKind.TRACE,
            execution_id=execution_id,
            source="span-a",
            target="span-b",
        )
        await runtime.save_observation(obs)
        listed = await runtime.list_for_execution(execution_id)
        assert [o.id for o in listed] == [obs.id]

    async def test_list_for_project(self, runtime: RuntimeEvidenceRepository) -> None:
        project_id = ProjectId(uuid.uuid4())
        obs = RuntimeObservation(
            kind=RuntimeEvidenceKind.LOG_EVENT,
            project_id=project_id,
            source="app",
            target="",
        )
        await runtime.save_observation(obs)
        listed = await runtime.list_for_project(project_id)
        assert [o.id for o in listed] == [obs.id]

    async def test_coverage_for_revision_groups_by_test(
        self, runtime: RuntimeEvidenceRepository
    ) -> None:
        await runtime.save_observation(_coverage("test_auth", "services/auth.py", ["auth.login"]))
        await runtime.save_observation(_coverage("test_auth", "services/token.py", ["token.issue"]))
        await runtime.save_observation(
            _coverage("test_billing", "billing/core.py", ["billing.charge"])
        )
        records = await runtime.coverage_for_revision(_REPOSITORY_ID, _REVISION)
        by_name = {record.test_name: record for record in records}
        assert set(by_name) == {"test_auth", "test_billing"}
        assert by_name["test_auth"].executed_files == [
            "services/auth.py",
            "services/token.py",
        ]
        assert by_name["test_auth"].executed_symbols == {
            "services/auth.py": ["auth.login"],
            "services/token.py": ["token.issue"],
        }

    async def test_dependencies_for_revision(self, runtime: RuntimeEvidenceRepository) -> None:
        await runtime.save_observation(_service_call("payments", "ledger"))
        await runtime.save_observation(_service_call("payments", "ledger"))
        await runtime.save_observation(_service_call("auth", "users-db"))
        deps = await runtime.dependencies_for_revision(_REPOSITORY_ID, _REVISION)
        by_key = {(d.relation, d.source, d.target): d for d in deps}
        assert by_key[("SERVICE_CALLS", "payments", "ledger")].evidence_count == 2
        assert by_key[("SERVICE_CALLS", "auth", "users-db")].evidence_count == 1

    async def test_observations_for_symbol(self, runtime: RuntimeEvidenceRepository) -> None:
        await runtime.save_observation(_coverage("test_auth", "services/auth.py", ["auth.login"]))
        await runtime.save_observation(
            _coverage("test_other", "billing/core.py", ["billing.charge"])
        )
        hits = await runtime.observations_for_symbol(_REPOSITORY_ID, _REVISION, "auth.login")
        assert len(hits) == 1
        assert hits[0].source == "test_auth"
