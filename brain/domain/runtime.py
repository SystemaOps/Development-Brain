"""Runtime intelligence domain model (Phase 19).

Enriches static understanding with observed behavior.  A
:class:`RuntimeObservation` is one observed fact (trace, coverage, log event,
service call, database access, message publish/consume).  Coverage maps
``test -> executed file -> executed symbol`` (Task 19.2); runtime dependencies
aggregate observations into graph edges (Task 19.4); the reconciliation result
combines static and runtime evidence while preserving both (Task 19.5); and the
advanced test selection picks targeted verification tests (Task 19.6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import ExecutionId, ProjectId, RepositoryId, WorkItemId


class RuntimeEvidenceKind(StrEnum):
    """The kinds of observed behavior the brain can ingest (Task 19.1)."""

    TRACE = "trace"
    COVERAGE = "coverage"
    LOG_EVENT = "log_event"
    SERVICE_CALL = "service_call"
    DATABASE_ACCESS = "database_access"
    MESSAGE_PUBLISH = "message_publish"
    MESSAGE_CONSUME = "message_consume"


class RuntimeObservation(BaseModel):
    """One observed runtime fact (Task 19.1).

    ``source`` names the observed origin (function / component / test); for
    coverage, ``source`` is the test name and ``target`` is the executed file,
    with ``symbols`` holding the executed symbol names where feasible.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    kind: RuntimeEvidenceKind
    project_id: ProjectId | None = None
    repository_id: RepositoryId | None = None
    revision: str | None = None
    execution_id: ExecutionId | None = None
    work_item_id: WorkItemId | None = None
    source: str = ""
    target: str = ""
    symbols: list[str] = Field(default_factory=list)
    detail: dict[str, object] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CoverageRecord(BaseModel):
    """``test -> executed file -> executed symbols`` mapping (Task 19.2)."""

    test_name: str
    test_path: str
    executed_files: list[str] = Field(default_factory=list)
    executed_symbols: dict[str, list[str]] = Field(default_factory=dict)  # file -> symbol names


class RuntimeDependency(BaseModel):
    """An observed dependency edge between two entities (Task 19.4)."""

    relation: str  # SERVICE_CALLS / QUERY_ACCESSES / PUBLISHES_TO / CONSUMES_FROM
    source: str
    target: str
    evidence_count: int = 1
    observations: list[uuid.UUID] = Field(default_factory=list)


class StaticRuntimeReconciliation(BaseModel):
    """Static vs runtime reconciliation for one symbol (Task 19.5).

    ``static_dependents`` comes from the parsed call graph; ``runtime_covers``
    lists tests/executions that actually exercised the symbol.  Both are
    preserved; ``combined_score`` blends them for ranking.
    """

    symbol: str
    static_dependents: list[str] = Field(default_factory=list)
    static_files: list[str] = Field(default_factory=list)
    runtime_covers: list[str] = Field(default_factory=list)
    runtime_files: list[str] = Field(default_factory=list)
    combined_score: float = 0.0


class TargetedTest(BaseModel):
    """One test selected by advanced test selection (Task 19.6)."""

    test_name: str
    path: str
    reasons: list[str] = Field(default_factory=list)
    score: float = 0.0


class AdvancedTestSelection(BaseModel):
    """The result of advanced test selection for a change set."""

    selected_tests: list[TargetedTest] = Field(default_factory=list)
    via_runtime_coverage: int = 0
    via_call_graph: int = 0
    via_changed_symbols: int = 0
    via_test_history: int = 0


__all__ = [
    "AdvancedTestSelection",
    "CoverageRecord",
    "RuntimeDependency",
    "RuntimeEvidenceKind",
    "RuntimeObservation",
    "StaticRuntimeReconciliation",
    "TargetedTest",
]
