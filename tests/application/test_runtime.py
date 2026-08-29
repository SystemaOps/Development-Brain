"""Phase 19 application tests: coverage import, OTEL traces, reconciliation, test selection."""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.runtime import InMemoryRuntimeEvidenceRepository
from brain.application.runtime import (
    AdvancedTestSelector,
    CoverageImporter,
    OtelTraceImporter,
    RuntimeEvidenceIngester,
    RuntimeReconciler,
)
from brain.domain.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    Symbol,
    SymbolIdentity,
    SymbolKind,
    SymbolLocation,
)
from brain.domain.identity import RepositoryId
from brain.domain.runtime import RuntimeEvidenceKind, RuntimeObservation


def _repository_id() -> RepositoryId:
    return RepositoryId(uuid.uuid4())


_TEST_RID = _repository_id()


def _symbol(name: str, path: str, kind: SymbolKind = SymbolKind.FUNCTION) -> Symbol:
    return Symbol(
        identity=SymbolIdentity(
            repository_id=_TEST_RID,
            revision="rev1",
            module=path.replace("/", ".").rsplit(".", 1)[0],
            qualified_name=name,
            kind=kind,
        ),
        name=name,
        path=path,
        kind=kind,
        qualified_name=name,
        location=SymbolLocation(path=path),
    )


def _test_symbol(name: str, path: str) -> Symbol:
    return _symbol(name, path, SymbolKind.FUNCTION)


async def test_ingester_records_observation() -> None:
    repo = InMemoryRuntimeEvidenceRepository()
    ingester = RuntimeEvidenceIngester(repository=repo)
    rid = _repository_id()
    obs = await ingester.record(
        kind=RuntimeEvidenceKind.SERVICE_CALL,
        repository_id=rid,
        revision="rev1",
        source="payments",
        target="ledger",
    )
    assert obs.source == "payments"
    assert obs.target == "ledger"
    listed = await repo.list_for_revision(rid, "rev1")
    assert len(listed) == 1


async def test_coverage_importer_maps_files_to_symbols() -> None:
    runtime = InMemoryRuntimeEvidenceRepository()
    code_graph = InMemoryCodeGraphRepository()
    rid = _TEST_RID
    await code_graph.save_symbols(
        [
            _symbol("auth.login", "services/auth.py"),
            _symbol("auth.logout", "services/auth.py"),
            _symbol("billing.charge", "billing/core.py"),
        ]
    )
    importer = CoverageImporter(repository=runtime, code_graph=code_graph)
    record = await importer.import_coverage(
        repository_id=rid,
        revision="rev1",
        test_name="test_auth",
        test_path="tests/test_auth.py",
        executed_files=["services/auth.py", "billing/core.py"],
    )
    assert record.executed_files == ["billing/core.py", "services/auth.py"]
    assert record.executed_symbols["services/auth.py"] == ["auth.login", "auth.logout"]
    assert record.executed_symbols["billing/core.py"] == ["billing.charge"]

    stored = await runtime.coverage_for_revision(rid, "rev1")
    assert stored[0].test_name == "test_auth"


async def test_otel_trace_importer_classifies_kinds() -> None:
    runtime = InMemoryRuntimeEvidenceRepository()
    importer = OtelTraceImporter(repository=runtime)
    rid = _repository_id()
    saved = await importer.ingest_trace(
        trace_id="trace-1",
        repository_id=rid,
        revision="rev1",
        spans=[
            {"name": "POST /payments", "kind": "server", "parent": "gw"},
            {
                "name": "SELECT users",
                "kind": "internal",
                "attributes": {"db.system": "postgres"},
            },
            {"name": "serialize", "kind": "internal"},
        ],
    )
    kinds = [obs.kind for obs in saved]
    assert kinds == [
        RuntimeEvidenceKind.SERVICE_CALL,
        RuntimeEvidenceKind.DATABASE_ACCESS,
        RuntimeEvidenceKind.TRACE,
    ]
    deps = await runtime.dependencies_for_revision(rid, "rev1")
    relations = {(d.relation, d.source, d.target) for d in deps}
    assert ("SERVICE_CALLS", "gw", "POST /payments") in relations
    assert ("QUERY_ACCESSES", "trace-1", "SELECT users") in relations


async def test_runtime_reconciler_preserves_static_and_runtime() -> None:
    runtime = InMemoryRuntimeEvidenceRepository()
    code_graph = InMemoryCodeGraphRepository()
    rid = _TEST_RID
    login = _symbol("auth.login", "services/auth.py")
    caller = _symbol("api.login_handler", "api/routes.py")
    test_sym = _test_symbol("test_login", "tests/test_auth.py")
    await code_graph.save_symbols([login, caller, test_sym])
    await code_graph.save_relations(
        [
            CodeRelation(
                relation_type=CodeRelationType.CALLS,
                source_identity=caller.identity,
                target_identity=login.identity,
                repository_id=rid,
                revision="rev1",
                source_path=caller.path,
                target_path=login.path,
            )
        ]
    )
    await runtime.save_observation(
        RuntimeObservation(
            kind=RuntimeEvidenceKind.COVERAGE,
            repository_id=rid,
            revision="rev1",
            source="test_login",
            target="services/auth.py",
            symbols=["auth.login"],
            detail={"test_path": "tests/test_auth.py"},
        )
    )

    reconciler = RuntimeReconciler(code_graph=code_graph, runtime=runtime)
    result = await reconciler.reconcile(rid, "rev1", "auth.login")
    assert result.static_dependents == ["api.login_handler"]
    assert result.static_files == ["api/routes.py"]
    assert result.runtime_covers == ["test_login"]
    assert result.runtime_files == ["services/auth.py"]
    assert result.combined_score > 0.5


async def test_advanced_test_selection_uses_call_graph_and_runtime() -> None:
    runtime = InMemoryRuntimeEvidenceRepository()
    code_graph = InMemoryCodeGraphRepository()
    rid = _TEST_RID
    login = _symbol("auth.login", "services/auth.py")
    test_auth = _test_symbol("test_auth.test_login", "tests/test_auth.py")
    test_billing = _test_symbol("test_billing.test_charge", "tests/test_billing.py")
    await code_graph.save_symbols([login, test_auth, test_billing])
    await code_graph.save_relations(
        [
            CodeRelation(
                relation_type=CodeRelationType.TESTS,
                source_identity=test_auth.identity,
                target_identity=login.identity,
                repository_id=rid,
                revision="rev1",
                source_path=test_auth.path,
                target_path=login.path,
            )
        ]
    )
    await runtime.save_observation(
        RuntimeObservation(
            kind=RuntimeEvidenceKind.COVERAGE,
            repository_id=rid,
            revision="rev1",
            source="test_auth.test_login",
            target="services/auth.py",
            symbols=["auth.login"],
        )
    )

    selector = AdvancedTestSelector(code_graph=code_graph, runtime=runtime)
    selection = await selector.select(rid, "rev1", ["auth.login"])
    names = [t.test_name for t in selection.selected_tests]
    assert "test_auth.test_login" in names
    assert selection.via_call_graph == 1
    assert selection.via_runtime_coverage == 1
