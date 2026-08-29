"""In-memory observability reference adapters (Phase 18)."""

from __future__ import annotations

from brain.domain.identity import ExecutionId
from brain.domain.observability import (
    ContextMetrics,
    ContextOutcomeSignals,
    ExecutionMetrics,
    ImpactAnalysisMetrics,
    LogEntry,
)


class InMemoryLogSink:
    """In-memory structured log sink."""

    def __init__(self) -> None:
        self.entries: list[LogEntry] = []

    async def append(self, entry: LogEntry) -> None:
        self.entries.append(entry)

    def list_recent(self, limit: int = 100) -> list[LogEntry]:
        return self.entries[-limit:]


class InMemoryMetricsRepository:
    """In-memory per-execution metrics storage."""

    def __init__(self) -> None:
        self.execution_metrics: dict[ExecutionId, ExecutionMetrics] = {}
        self.context_metrics: dict[ExecutionId, ContextMetrics] = {}
        self.context_outcomes: dict[ExecutionId, ContextOutcomeSignals] = {}
        self.impact_metrics: dict[ExecutionId, ImpactAnalysisMetrics] = {}

    async def save_execution_metrics(self, metrics: ExecutionMetrics) -> None:
        self.execution_metrics[metrics.execution_id] = metrics

    async def get_execution_metrics(self, execution_id: ExecutionId) -> ExecutionMetrics | None:
        return self.execution_metrics.get(execution_id)

    async def save_context_metrics(self, metrics: ContextMetrics) -> None:
        if metrics.execution_id is not None:
            self.context_metrics[metrics.execution_id] = metrics

    async def get_context_metrics(self, execution_id: ExecutionId) -> ContextMetrics | None:
        return self.context_metrics.get(execution_id)

    async def save_context_outcome(self, signals: ContextOutcomeSignals) -> None:
        self.context_outcomes[signals.execution_id] = signals

    async def get_context_outcome(self, execution_id: ExecutionId) -> ContextOutcomeSignals | None:
        return self.context_outcomes.get(execution_id)

    async def save_impact_metrics(self, metrics: ImpactAnalysisMetrics) -> None:
        self.impact_metrics[metrics.execution_id] = metrics

    async def get_impact_metrics(self, execution_id: ExecutionId) -> ImpactAnalysisMetrics | None:
        return self.impact_metrics.get(execution_id)
