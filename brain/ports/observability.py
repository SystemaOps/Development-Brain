"""Observability and metrics ports (Phase 18).

``LogSink`` records structured log entries; ``MetricsRepository`` persists the
per-execution metric records (execution, context, context-outcome, impact)
that feed the Phase 18 completion gate and the metrics dashboard.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import ExecutionId
from brain.domain.observability import (
    ContextMetrics,
    ContextOutcomeSignals,
    ExecutionMetrics,
    ImpactAnalysisMetrics,
    LogEntry,
)


@runtime_checkable
class LogSink(Protocol):
    async def append(self, entry: LogEntry) -> None: ...


@runtime_checkable
class MetricsRepository(Protocol):
    async def save_execution_metrics(self, metrics: ExecutionMetrics) -> None: ...

    async def get_execution_metrics(self, execution_id: ExecutionId) -> ExecutionMetrics | None: ...

    async def save_context_metrics(self, metrics: ContextMetrics) -> None: ...

    async def get_context_metrics(self, execution_id: ExecutionId) -> ContextMetrics | None: ...

    async def save_context_outcome(self, signals: ContextOutcomeSignals) -> None: ...

    async def get_context_outcome(
        self, execution_id: ExecutionId
    ) -> ContextOutcomeSignals | None: ...

    async def save_impact_metrics(self, metrics: ImpactAnalysisMetrics) -> None: ...

    async def get_impact_metrics(
        self, execution_id: ExecutionId
    ) -> ImpactAnalysisMetrics | None: ...


__all__ = ["LogSink", "MetricsRepository"]
