"""Observability application services (Phase 18).

- :class:`StructuredLogger` binds ids (project / workflow / work item /
  execution / correlation) to every emitted log event (Task 18.1).
- :class:`MetricsCollector` records execution, context, context-outcome and
  impact metrics through the ``MetricsRepository`` port (Tasks 18.2-18.5).
- :class:`MetricsReporter` exposes a Grafana-compatible text format and a
  JSON snapshot per execution (Task 18.6).
- :class:`ObservabilityService.reconstruct_execution` builds the Phase 18
  completion-gate snapshot: context selected, why, model, changes, verdict.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime

from brain.domain.context import ContextCandidate
from brain.domain.identity import ContextCapsuleId, ExecutionId, WorkItemId
from brain.domain.observability import (
    ContextMetrics,
    ContextOutcomeSignals,
    ExecutionMetrics,
    ImpactAnalysisMetrics,
    LogContext,
    LogEntry,
    LogLevel,
    MetricsSnapshot,
    SelectedContextItem,
)
from brain.domain.verification_plan import VerificationRun
from brain.ports.observability import LogSink, MetricsRepository


class StructuredLogger:
    """Emits structured log entries carrying available ids (Task 18.1)."""

    def __init__(
        self,
        *,
        sink: LogSink,
        context: LogContext | None = None,
    ) -> None:
        self._sink = sink
        self._context = context or LogContext()

    def bind(self, **ids: uuid.UUID | None) -> StructuredLogger:
        context = self._context.model_copy(
            update={key: value for key, value in ids.items() if value is not None}
        )
        return StructuredLogger(sink=self._sink, context=context)

    async def log(
        self,
        level: LogLevel,
        event: str,
        message: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> None:
        entry = LogEntry(
            level=level,
            event=event,
            message=message,
            context=self._context,
            payload=payload or {},
        )
        await self._sink.append(entry)

    async def debug(self, event: str, message: str, **kwargs: object) -> None:
        await self.log(LogLevel.DEBUG, event, message, payload=kwargs)

    async def info(self, event: str, message: str, **kwargs: object) -> None:
        await self.log(LogLevel.INFO, event, message, payload=kwargs)

    async def warning(self, event: str, message: str, **kwargs: object) -> None:
        await self.log(LogLevel.WARNING, event, message, payload=kwargs)

    async def error(self, event: str, message: str, **kwargs: object) -> None:
        await self.log(LogLevel.ERROR, event, message, payload=kwargs)


class MetricsCollector:
    """Records per-execution observability metrics (Tasks 18.2-18.5)."""

    def __init__(self, *, metrics: MetricsRepository) -> None:
        self._metrics = metrics

    async def record_execution_metrics(self, metrics: ExecutionMetrics) -> None:
        await self._metrics.save_execution_metrics(metrics)

    async def record_context_metrics(self, metrics: ContextMetrics) -> None:
        await self._metrics.save_context_metrics(metrics)

    async def record_context_outcome(self, signals: ContextOutcomeSignals) -> None:
        await self._metrics.save_context_outcome(signals)

    async def record_impact_metrics(self, metrics: ImpactAnalysisMetrics) -> None:
        await self._metrics.save_impact_metrics(metrics)


class ContextMetricsBuilder:
    """Builds :class:`ContextMetrics` from a built capsule's candidates."""

    @staticmethod
    def build(
        *,
        context_capsule_id: ContextCapsuleId,
        work_item_id: WorkItemId,
        execution_id: ExecutionId | None,
        context_token_count: int,
        candidates_gathered: int,
        selected: list[ContextCandidate],
        jit_retrieval_requests: int = 0,
    ) -> ContextMetrics:
        distribution = Counter(candidate.retrieval_source.value for candidate in selected)
        selected_context = [
            SelectedContextItem(
                entity_type=candidate.entity_type,
                entity_id=candidate.entity_id,
                reason=candidate.reason,
                retrieval_source=candidate.retrieval_source.value,
                relevance_score=candidate.relevance_score,
            )
            for candidate in selected
        ]
        return ContextMetrics(
            context_capsule_id=context_capsule_id,
            work_item_id=work_item_id,
            execution_id=execution_id,
            context_token_count=context_token_count,
            candidate_count=candidates_gathered,
            selected_entity_count=len(selected),
            retrieval_source_distribution=dict(distribution),
            jit_retrieval_requests=jit_retrieval_requests,
            selected_context=selected_context,
        )


class ContextOutcomeEvaluator:
    """Derives context-quality outcome signals (Task 18.4)."""

    @staticmethod
    def evaluate(
        *,
        execution_id: ExecutionId,
        selected_paths: list[str],
        changed_files: list[str],
        additional_context_requests: int = 0,
        irrelevant_context_rate: float = 0.0,
        retry_caused_by_context_failure: bool = False,
    ) -> ContextOutcomeSignals:
        selected = set(selected_paths)
        changed = set(changed_files)
        missing = sorted(changed - selected)
        return ContextOutcomeSignals(
            execution_id=execution_id,
            missing_files_discovered_later=missing,
            verifier_omitted_dependencies=missing,
            additional_context_requests=additional_context_requests,
            irrelevant_context_rate=irrelevant_context_rate,
            retry_caused_by_context_failure=retry_caused_by_context_failure,
        )


class MetricsReporter:
    """Exposes metrics through a Grafana-compatible text format (Task 18.6)."""

    def __init__(self, *, metrics: MetricsRepository) -> None:
        self._metrics = metrics

    def render_prometheus(self, execution: ExecutionMetrics) -> str:
        """Render one execution's metrics in the Prometheus text exposition format."""
        lines = [
            "# TYPE brain_execution_duration_seconds gauge",
            f'brain_execution_duration_seconds{{execution_id="{execution.execution_id}"}} '
            f"{execution.duration_seconds or 0.0}",
            "# TYPE brain_execution_tokens_in counter",
            f'brain_execution_tokens_in{{execution_id="{execution.execution_id}"}} '
            f"{execution.tokens_in}",
            "# TYPE brain_execution_tokens_out counter",
            f'brain_execution_tokens_out{{execution_id="{execution.execution_id}"}} '
            f"{execution.tokens_out}",
            "# TYPE brain_execution_tool_calls counter",
            f'brain_execution_tool_calls{{execution_id="{execution.execution_id}"}} '
            f"{execution.tool_calls}",
            "# TYPE brain_execution_retries counter",
            f'brain_execution_retries{{execution_id="{execution.execution_id}"}} '
            f"{execution.retries}",
        ]
        return "\n".join(lines)


class ObservabilityService:
    """Coordinates metrics recording and the completion-gate snapshot."""

    def __init__(
        self,
        *,
        metrics: MetricsRepository,
        logs: LogSink,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._metrics = metrics
        self._logs = logs
        self._logger = logger or StructuredLogger(sink=logs)

    async def reconstruct_execution(self, execution_id: ExecutionId) -> MetricsSnapshot | None:
        """Build the Phase 18 completion-gate snapshot for one execution."""
        execution = await self._metrics.get_execution_metrics(execution_id)
        if execution is None:
            return None
        context = await self._metrics.get_context_metrics(execution_id)
        outcome = await self._metrics.get_context_outcome(execution_id)
        impact = await self._metrics.get_impact_metrics(execution_id)

        changed = impact.actual_changed_files if impact else execution.commands_executed
        verdict = None
        reasons: list[str] = []
        if execution.verification_outcome:
            verdict = execution.verification_outcome
            reasons = ["verification outcome recorded"]

        return MetricsSnapshot(
            execution_id=execution_id,
            workflow_id=execution.workflow_id,
            work_item_id=execution.work_item_id,
            project_id=execution.project_id,
            model=execution.model,
            changed_files=changed,
            verification_verdict=verdict,
            verification_reasons=reasons,
            selected_context=context.selected_context if context else [],
            context_token_count=context.context_token_count if context else 0,
            execution=execution,
            context=context,
            outcome=outcome,
            impact=impact,
        )

    async def record_verification_run(
        self, run: VerificationRun, execution_id: ExecutionId
    ) -> None:
        """Attach a verification verdict to an execution's metrics."""
        execution = await self._metrics.get_execution_metrics(execution_id)
        if execution is None:
            return
        execution.verification_outcome = run.verdict.value
        execution.completed_at = datetime.now(UTC)
        execution.duration_seconds = (execution.completed_at - execution.started_at).total_seconds()
        await self._metrics.save_execution_metrics(execution)


__all__ = [
    "ContextMetricsBuilder",
    "ContextOutcomeEvaluator",
    "MetricsCollector",
    "MetricsReporter",
    "ObservabilityService",
    "StructuredLogger",
]
