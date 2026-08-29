"""Phase 18 golden tests and completion gate.

For an execution, a developer can reconstruct what context was selected, why
it was selected, what model executed, what changed, and why verification
passed or failed.
"""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.observability import (
    InMemoryLogSink,
    InMemoryMetricsRepository,
)
from brain.application.observability import (
    ContextMetricsBuilder,
    ContextOutcomeEvaluator,
    ObservabilityService,
    StructuredLogger,
)
from brain.domain.context import (
    ContextCandidate,
    ContextCategory,
    RetrievalSource,
)
from brain.domain.identity import (
    ContextCapsuleId,
    ExecutionId,
    WorkItemId,
)
from brain.domain.observability import (
    ExecutionMetrics,
    ImpactAnalysisMetrics,
)


def _candidate(reason: str, entity_type: str = "Symbol") -> ContextCandidate:
    return ContextCandidate(
        entity_id=uuid.uuid4(),
        entity_type=entity_type,
        content="services/auth.py" if entity_type == "Symbol" else "REQ-1",
        reason=reason,
        retrieval_source=(
            RetrievalSource.CODE_GRAPH if entity_type == "Symbol" else RetrievalSource.REQUIREMENT
        ),
        relevance_score=0.9,
        category=(
            ContextCategory.SOURCE_CODE if entity_type == "Symbol" else ContextCategory.REQUIREMENTS
        ),
    )


async def test_gate_reconstructs_execution_trace() -> None:
    metrics_repo = InMemoryMetricsRepository()
    logs = InMemoryLogSink()
    logger = StructuredLogger(sink=logs)
    service = ObservabilityService(metrics=metrics_repo, logs=logs, logger=logger)

    execution_id = ExecutionId(uuid.uuid4())
    workflow_id = uuid.uuid4()
    work_item_id = WorkItemId(uuid.uuid4())
    capsule_id = ContextCapsuleId(uuid.uuid4())

    # Execution: model, duration, tokens, retries, verification verdict.
    await metrics_repo.save_execution_metrics(
        ExecutionMetrics(
            execution_id=execution_id,
            workflow_id=workflow_id,
            work_item_id=work_item_id,
            model="gpt-4o",
            tokens_in=512,
            tokens_out=1024,
            tool_calls=6,
            commands_executed=["ruff check", "pytest -q"],
            retries=1,
            verification_outcome="pass",
            duration_seconds=42.0,
        )
    )

    # Context: what was selected and why.
    selected = [
        _candidate("contains primary impacted symbol"),
        _candidate("auth requirement", "Requirement"),
    ]
    await metrics_repo.save_context_metrics(
        ContextMetricsBuilder.build(
            context_capsule_id=capsule_id,
            work_item_id=work_item_id,
            execution_id=execution_id,
            context_token_count=3100,
            candidates_gathered=18,
            selected=selected,
            jit_retrieval_requests=1,
        )
    )

    # Outcome: verification found an omitted dependency.
    await metrics_repo.save_context_outcome(
        ContextOutcomeEvaluator.evaluate(
            execution_id=execution_id,
            selected_paths=["services/auth.py"],
            changed_files=["services/auth.py", "services/token.py"],
            additional_context_requests=1,
            irrelevant_context_rate=0.1,
            retry_caused_by_context_failure=False,
        )
    )

    # Impact: predicted vs actual.
    await metrics_repo.save_impact_metrics(
        ImpactAnalysisMetrics(
            execution_id=execution_id,
            predicted_files=["services/auth.py"],
            actual_changed_files=["services/auth.py", "services/token.py"],
        )
    )

    # Structured logs carrying ids (Task 18.1).
    await logger.bind(
        workflow_id=workflow_id, execution_id=execution_id, work_item_id=work_item_id
    ).info("execution.completed", "execution completed", model="gpt-4o")

    snapshot = await service.reconstruct_execution(execution_id)
    assert snapshot is not None

    # Completion gate: model executed.
    assert snapshot.model == "gpt-4o"
    assert snapshot.execution is not None
    assert snapshot.execution.retries == 1

    # Completion gate: what changed.
    assert snapshot.changed_files == ["services/auth.py", "services/token.py"]

    # Completion gate: why verification passed.
    assert snapshot.verification_verdict == "pass"
    assert snapshot.verification_reasons

    # Completion gate: what context was selected and why.
    assert snapshot.context is not None
    reasons = [item.reason for item in snapshot.selected_context]
    assert "contains primary impacted symbol" in reasons
    assert "auth requirement" in reasons
    assert snapshot.context.context_token_count == 3100

    # Completion gate: context quality signals.
    assert snapshot.outcome is not None
    assert snapshot.outcome.missing_files_discovered_later == ["services/token.py"]

    # Structured logs are traceable through the correlation chain.
    assert len(logs.entries) == 1
    assert logs.entries[0].context.workflow_id == workflow_id
    assert logs.entries[0].context.execution_id == execution_id


async def test_gate_logs_flow_through_correlation_chain() -> None:
    logs = InMemoryLogSink()
    logger = StructuredLogger(sink=logs)
    correlation_id = uuid.uuid4()
    await logger.bind(correlation_id=correlation_id).info("ingestion.start", "ingesting")
    await logger.bind(correlation_id=correlation_id).info("context.build", "building context")
    await logger.bind(correlation_id=correlation_id).error("execution.failed", "boom")

    chain = [entry.event for entry in logs.entries]
    assert chain == ["ingestion.start", "context.build", "execution.failed"]
    assert all(entry.context.correlation_id == correlation_id for entry in logs.entries)


async def test_gate_prometheus_metrics_format() -> None:
    from brain.application.observability import MetricsReporter

    metrics_repo = InMemoryMetricsRepository()
    reporter = MetricsReporter(metrics=metrics_repo)
    execution_id = ExecutionId(uuid.uuid4())
    execution = ExecutionMetrics(
        execution_id=execution_id,
        model="gpt-4o",
        tokens_in=100,
        tokens_out=200,
        tool_calls=3,
        retries=0,
        duration_seconds=9.5,
    )
    text = reporter.render_prometheus(execution)
    assert "brain_execution_duration_seconds" in text
    assert 'execution_id="' in text
    assert "brain_execution_tokens_in" in text
    assert "brain_execution_retries" in text
