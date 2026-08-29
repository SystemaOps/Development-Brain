"""Phase 19 golden tests and completion gate.

The brain can explain both "what code may depend on a symbol" (static call
graph) and "what tests/runtime paths actually exercised it" (runtime coverage
and observations).
"""

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
from brain.domain.runtime import RuntimeEvidenceKind


def _symbol(name: str, path: str) -> Symbol:
    return Symbol(
        identity=SymbolIdentity(
            repository_id=_RID,
            revision="rev1",
            module=path.replace("/", ".").rsplit(".", 1)[0],
            qualified_name=name,
            kind=SymbolKind.FUNCTION,
        ),
        name=name,
        path=path,
        kind=SymbolKind.FUNCTION,
        qualified_name=name,
        location=SymbolLocation(path=path),
    )


_RID = RepositoryId(uuid.uuid4())


async def test_gate_static_and_runtime_explanation_for_symbol() -> None:
    runtime = InMemoryRuntimeEvidenceRepository()
    code_graph = InMemoryCodeGraphRepository()

    login = _symbol("auth.login", "services/auth.py")
    handler = _symbol("api.login_handler", "api/routes.py")
    test_login = _symbol("test_auth.test_login", "tests/test_auth.py")
    await code_graph.save_symbols([login, handler, test_login])
    await code_graph.save_relations(
        [
            CodeRelation(
                relation_type=CodeRelationType.CALLS,
                source_identity=handler.identity,
                target_identity=login.identity,
                repository_id=_RID,
                revision="rev1",
                source_path=handler.path,
                target_path=login.path,
            ),
            CodeRelation(
                relation_type=CodeRelationType.TESTS,
                source_identity=test_login.identity,
                target_identity=login.identity,
                repository_id=_RID,
                revision="rev1",
                source_path=test_login.path,
                target_path=login.path,
            ),
        ]
    )

    # Runtime: coverage exercised auth.login; an OTEL trace observed a
    # service call from payments to ledger.
    importer = CoverageImporter(repository=runtime, code_graph=code_graph)
    await importer.import_coverage(
        repository_id=_RID,
        revision="rev1",
        test_name="test_auth.test_login",
        test_path="tests/test_auth.py",
        executed_files=["services/auth.py"],
    )
    otel = OtelTraceImporter(repository=runtime)
    await otel.ingest_trace(
        trace_id="trace-1",
        repository_id=_RID,
        revision="rev1",
        spans=[
            {"name": "POST /payments", "kind": "server", "parent": "gw"},
            {"name": "SELECT users", "kind": "internal", "attributes": {"db.system": "postgres"}},
        ],
    )

    # Gate part 1: what code may depend on the symbol (static).
    reconciler = RuntimeReconciler(code_graph=code_graph, runtime=runtime)
    result = await reconciler.reconcile(_RID, "rev1", "auth.login")
    assert result.static_dependents == ["api.login_handler"]
    assert result.static_files == ["api/routes.py"]

    # Gate part 2: what tests/runtime paths actually exercised it.
    assert result.runtime_covers == ["test_auth.test_login"]
    assert "services/auth.py" in result.runtime_files
    assert result.combined_score > 0.5

    # Runtime dependency graph reflects observed service + db relations.
    deps = await runtime.dependencies_for_revision(_RID, "rev1")
    relations = {(d.relation, d.source, d.target) for d in deps}
    assert ("SERVICE_CALLS", "gw", "POST /payments") in relations
    assert ("QUERY_ACCESSES", "trace-1", "SELECT users") in relations

    # Advanced test selection targets the changed symbol.
    selector = AdvancedTestSelector(code_graph=code_graph, runtime=runtime)
    selection = await selector.select(_RID, "rev1", ["auth.login"])
    names = [t.test_name for t in selection.selected_tests]
    assert "test_auth.test_login" in names
    assert selection.via_call_graph >= 1
    assert selection.via_runtime_coverage >= 1


async def test_gate_ingester_records_message_publish_consume() -> None:
    runtime = InMemoryRuntimeEvidenceRepository()
    ingester = RuntimeEvidenceIngester(repository=runtime)
    await ingester.record(
        kind=RuntimeEvidenceKind.MESSAGE_PUBLISH,
        repository_id=_RID,
        revision="rev1",
        source="orders",
        target="order-events",
    )
    await ingester.record(
        kind=RuntimeEvidenceKind.MESSAGE_CONSUME,
        repository_id=_RID,
        revision="rev1",
        source="inventory",
        target="order-events",
    )
    deps = await runtime.dependencies_for_revision(_RID, "rev1")
    relations = {(d.relation, d.source, d.target) for d in deps}
    assert ("PUBLISHES_TO", "orders", "order-events") in relations
    assert ("CONSUMES_FROM", "inventory", "order-events") in relations
