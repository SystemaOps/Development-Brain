"""Runtime intelligence application services (Phase 19).

- :class:`RuntimeEvidenceIngester` records observed behavior and groups it into
  coverage records and dependency edges.
- :class:`CoverageImporter` maps ``test -> executed file -> executed symbol``
  using the parsed code graph (Task 19.2).
- :class:`OtelTraceImporter` ingests safe development/test traces and emits
  runtime observations (Task 19.3).
- :class:`RuntimeReconciler` combines static (call graph) and runtime evidence
  while preserving both (Task 19.5).
- :class:`AdvancedTestSelector` selects targeted verification tests using
  changed symbols, the call graph, runtime coverage, and test history
  (Task 19.6).
"""

from __future__ import annotations

from collections import defaultdict

from brain.domain.code_intelligence import CodeRelationType
from brain.domain.identity import (
    ExecutionId,
    ProjectId,
    RepositoryId,
    WorkItemId,
)
from brain.domain.runtime import (
    AdvancedTestSelection,
    CoverageRecord,
    RuntimeDependency,
    RuntimeEvidenceKind,
    RuntimeObservation,
    StaticRuntimeReconciliation,
    TargetedTest,
)
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.runtime import RuntimeEvidenceRepository


class RuntimeEvidenceIngester:
    """Ingests observed runtime facts and derives coverage/dependencies."""

    def __init__(self, *, repository: RuntimeEvidenceRepository) -> None:
        self._repository = repository

    async def record(
        self,
        *,
        kind: RuntimeEvidenceKind,
        repository_id: RepositoryId | None = None,
        revision: str | None = None,
        execution_id: ExecutionId | None = None,
        project_id: ProjectId | None = None,
        work_item_id: WorkItemId | None = None,
        source: str = "",
        target: str = "",
        symbols: list[str] | None = None,
        detail: dict[str, object] | None = None,
    ) -> RuntimeObservation:
        observation = RuntimeObservation(
            kind=kind,
            repository_id=repository_id,
            revision=revision,
            execution_id=execution_id,
            project_id=project_id,
            work_item_id=work_item_id,
            source=source,
            target=target,
            symbols=symbols or [],
            detail=detail or {},
        )
        return await self._repository.save_observation(observation)

    async def coverage_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[CoverageRecord]:
        return await self._repository.coverage_for_revision(repository_id, revision)

    async def dependencies_for_revision(
        self, repository_id: RepositoryId, revision: str
    ) -> list[RuntimeDependency]:
        return await self._repository.dependencies_for_revision(repository_id, revision)


class CoverageImporter:
    """Maps test coverage lines to executed files/symbols (Task 19.2)."""

    def __init__(
        self, *, repository: RuntimeEvidenceRepository, code_graph: CodeGraphRepository
    ) -> None:
        self._repository = repository
        self._code_graph = code_graph

    async def import_coverage(
        self,
        *,
        repository_id: RepositoryId,
        revision: str,
        test_name: str,
        test_path: str,
        executed_files: list[str],
        execution_id: ExecutionId | None = None,
        project_id: ProjectId | None = None,
    ) -> CoverageRecord:
        symbols = await self._code_graph.list_symbols(repository_id, revision)
        by_path: dict[str, list[str]] = defaultdict(list)
        for symbol in symbols:
            if symbol.path in executed_files:
                by_path[symbol.path].append(symbol.qualified_name)

        for path in executed_files:
            await self._repository.save_observation(
                RuntimeObservation(
                    kind=RuntimeEvidenceKind.COVERAGE,
                    repository_id=repository_id,
                    revision=revision,
                    execution_id=execution_id,
                    project_id=project_id,
                    source=test_name,
                    target=path,
                    symbols=by_path.get(path, []),
                    detail={"test_path": test_path},
                )
            )

        record = CoverageRecord(
            test_name=test_name,
            test_path=test_path,
            executed_files=sorted(set(executed_files)),
            executed_symbols={path: sorted(set(symbols)) for path, symbols in by_path.items()},
        )
        return record


class OtelTraceImporter:
    """Ingests OpenTelemetry-style trace spans (Task 19.3).

    Accepts safe development/test trace spans in a normalized dict form and
    persists them as runtime observations so the runtime dependency graph and
    coverage analysis can use them.
    """

    def __init__(self, *, repository: RuntimeEvidenceRepository) -> None:
        self._repository = repository

    async def ingest_trace(
        self,
        *,
        trace_id: str,
        spans: list[dict[str, object]],
        repository_id: RepositoryId | None = None,
        revision: str | None = None,
        execution_id: ExecutionId | None = None,
        project_id: ProjectId | None = None,
    ) -> list[RuntimeObservation]:
        saved: list[RuntimeObservation] = []
        for span in spans:
            name = str(span.get("name", "span"))
            kind_value = span.get("kind", "internal")
            attributes = span.get("attributes", {})
            db_system = str(attributes.get("db.system", "")) if isinstance(attributes, dict) else ""
            if kind_value == "server" or "client" in str(kind_value):
                kind = RuntimeEvidenceKind.SERVICE_CALL
            elif db_system:
                kind = RuntimeEvidenceKind.DATABASE_ACCESS
            else:
                kind = RuntimeEvidenceKind.TRACE
            observation = await self._repository.save_observation(
                RuntimeObservation(
                    kind=kind,
                    repository_id=repository_id,
                    revision=revision,
                    execution_id=execution_id,
                    project_id=project_id,
                    source=str(span.get("parent", "")) or trace_id,
                    target=name,
                    detail={"trace_id": trace_id, **span},
                )
            )
            saved.append(observation)
        return saved


class RuntimeReconciler:
    """Combines static and runtime evidence while preserving both (Task 19.5)."""

    def __init__(
        self, *, code_graph: CodeGraphRepository, runtime: RuntimeEvidenceRepository
    ) -> None:
        self._code_graph = code_graph
        self._runtime = runtime

    async def reconcile(
        self,
        repository_id: RepositoryId,
        revision: str,
        symbol: str,
    ) -> StaticRuntimeReconciliation:
        relations = await self._code_graph.list_relations(repository_id, revision)

        static_dependents = sorted(
            {
                rel.source_identity.qualified_name
                for rel in relations
                if rel.relation_type == CodeRelationType.CALLS
                and rel.target_identity.qualified_name == symbol
            }
        )
        static_files = sorted(
            {
                rel.source_path
                for rel in relations
                if rel.relation_type == CodeRelationType.CALLS
                and rel.target_identity.qualified_name == symbol
            }
        )

        observations = await self._runtime.observations_for_symbol(repository_id, revision, symbol)
        runtime_covers = sorted(
            {
                obs.source
                for obs in observations
                if obs.source and obs.kind == RuntimeEvidenceKind.COVERAGE
            }
        )
        runtime_files = sorted({obs.target for obs in observations if obs.target})

        score = min(1.0, 0.5 + 0.1 * len(runtime_covers) + 0.05 * len(static_dependents))
        return StaticRuntimeReconciliation(
            symbol=symbol,
            static_dependents=static_dependents,
            static_files=static_files,
            runtime_covers=runtime_covers,
            runtime_files=runtime_files,
            combined_score=round(score, 2),
        )


class AdvancedTestSelector:
    """Selects targeted verification tests (Task 19.6)."""

    def __init__(
        self,
        *,
        code_graph: CodeGraphRepository,
        runtime: RuntimeEvidenceRepository,
    ) -> None:
        self._code_graph = code_graph
        self._runtime = runtime

    async def select(
        self,
        repository_id: RepositoryId,
        revision: str,
        changed_symbols: list[str],
        test_history: list[str] | None = None,
    ) -> AdvancedTestSelection:
        symbols = await self._code_graph.list_symbols(repository_id, revision)
        relations = await self._code_graph.list_relations(repository_id, revision)

        tests_by_symbol: dict[str, list[str]] = defaultdict(list)
        for relation in relations:
            if relation.relation_type == CodeRelationType.TESTS:
                target = relation.target_identity.qualified_name
                source = relation.source_identity.qualified_name
                if _is_test_name(source):
                    tests_by_symbol[target].append(source)

        test_paths: dict[str, str] = {
            symbol.qualified_name: symbol.path
            for symbol in symbols
            if _is_test_name(symbol.qualified_name)
        }

        selected: dict[str, TargetedTest] = {}
        via_runtime = 0
        via_call_graph = 0
        via_changed = 0
        via_history = 0

        for changed in changed_symbols:
            for test in tests_by_symbol.get(changed, []):
                if test not in selected:
                    selected[test] = TargetedTest(
                        test_name=test,
                        path=test_paths.get(test, ""),
                        reasons=[],
                        score=0.0,
                    )
                    via_call_graph += 1
                selected[test].reasons.append(f"tests {changed} via call graph")
                selected[test].score += 0.5

        observations = await self._runtime.list_for_revision(repository_id, revision)
        covered_tests = {
            obs.source
            for obs in observations
            if obs.kind == RuntimeEvidenceKind.COVERAGE and set(obs.symbols) & set(changed_symbols)
        }
        for test in covered_tests:
            if test not in selected:
                selected[test] = TargetedTest(
                    test_name=test,
                    path=test_paths.get(test, ""),
                    reasons=[],
                    score=0.0,
                )
            if "runtime coverage" not in selected[test].reasons:
                selected[test].reasons.append("exercised changed symbols at runtime")
                selected[test].score += 0.8
                via_runtime += 1

        history = set(test_history or [])
        for test in history:
            if test not in selected:
                selected[test] = TargetedTest(
                    test_name=test,
                    path=test_paths.get(test, ""),
                    reasons=["historical failure"],
                    score=0.3,
                )
                via_history += 1

        return AdvancedTestSelection(
            selected_tests=sorted(selected.values(), key=lambda t: t.score, reverse=True),
            via_runtime_coverage=via_runtime,
            via_call_graph=via_call_graph,
            via_changed_symbols=via_changed,
            via_test_history=via_history,
        )


def _is_test_name(qualified_name: str) -> bool:
    last = qualified_name.rsplit(".", 1)[-1]
    return last.startswith("test_") or last.startswith("Test")


__all__ = [
    "AdvancedTestSelector",
    "CoverageImporter",
    "OtelTraceImporter",
    "RuntimeEvidenceIngester",
    "RuntimeReconciler",
]
