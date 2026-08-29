"""Phase 18 application tests: structured logging, metrics, outcome evaluation."""

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
    ContextMetrics,
    ContextOutcomeSignals,
    ExecutionMetrics,
    ImpactAnalysisMetrics,
    LogLevel,
)
from brain.domain.verification_plan import (
    VerificationPlan,
    VerificationRun,
    VerificationVerdict,
)


async def test_structured_logger_carries_context() -> None:
    sink = InMemoryLogSink()
    logger = StructuredLogger(sink=sink)
    workflow_id = uuid.uuid4()
    bound = logger.bind(workflow_id=workflow_id)
    await bound.info("execution.started", "execution started", model="gpt-4o")

    assert len(sink.entries) == 1
    entry = sink.entries[0]
    assert entry.level == LogLevel.INFO
    assert entry.event == "execution.started"
    assert entry.context.workflow_id == workflow_id
    assert entry.payload["model"] == "gpt-4o"


async def test_context_metrics_builder() -> None:
    execution_id = ExecutionId(uuid.uuid4())
    work_item_id = WorkItemId(uuid.uuid4())
    capsule_id = ContextCapsuleId(uuid.uuid4())
    selected = [
        ContextCandidate(
            entity_id=uuid.uuid4(),
            entity_type="Symbol",
            content="services/auth.py",
            reason="contains primary impacted symbol",
            retrieval_source=RetrievalSource.CODE_GRAPH,
            relevance_score=0.9,
            category=ContextCategory.SOURCE_CODE,
        ),
        ContextCandidate(
            entity_id=uuid.uuid4(),
            entity_type="Requirement",
            content="REQ-1",
            reason="requirement referenced by task",
            retrieval_source=RetrievalSource.REQUIREMENT,
            relevance_score=0.95,
            category=ContextCategory.REQUIREMENTS,
        ),
    ]
    metrics = ContextMetricsBuilder.build(
        context_capsule_id=capsule_id,
        work_item_id=work_item_id,
        execution_id=execution_id,
        context_token_count=2000,
        candidates_gathered=10,
        selected=selected,
        jit_retrieval_requests=3,
    )
    assert metrics.selected_entity_count == 2
    assert metrics.candidate_count == 10
    assert metrics.retrieval_source_distribution == {"code_graph": 1, "requirement": 1}
    assert metrics.jit_retrieval_requests == 3
    assert metrics.selected_context[0].reason == "contains primary impacted symbol"


async def test_context_outcome_evaluator_detects_missing_files() -> None:
    execution_id = ExecutionId(uuid.uuid4())
    signals = ContextOutcomeEvaluator.evaluate(
        execution_id=execution_id,
        selected_paths=["src/a.py"],
        changed_files=["src/a.py", "src/omitted.py"],
        additional_context_requests=1,
        irrelevant_context_rate=0.1,
        retry_caused_by_context_failure=True,
    )
    assert signals.missing_files_discovered_later == ["src/omitted.py"]
    assert signals.verifier_omitted_dependencies == ["src/omitted.py"]
    assert signals.additional_context_requests == 1
    assert signals.retry_caused_by_context_failure is True


async def test_impact_metrics_false_positives_and_negatives() -> None:
    execution_id = ExecutionId(uuid.uuid4())
    metrics = ImpactAnalysisMetrics(
        execution_id=execution_id,
        predicted_files=["src/a.py", "src/b.py"],
        actual_changed_files=["src/a.py", "src/c.py"],
    )
    assert metrics.false_positives == ["src/b.py"]
    assert metrics.false_negatives == ["src/c.py"]


async def test_observability_service_reconstructs_execution() -> None:
    metrics_repo = InMemoryMetricsRepository()
    logs = InMemoryLogSink()
    service = ObservabilityService(metrics=metrics_repo, logs=logs)

    execution_id = ExecutionId(uuid.uuid4())
    await metrics_repo.save_execution_metrics(
        ExecutionMetrics(
            execution_id=execution_id,
            workflow_id=uuid.uuid4(),
            model="gpt-4o",
            tokens_in=100,
            tokens_out=200,
            tool_calls=3,
            commands_executed=["ruff"],
            retries=0,
            verification_outcome="pass",
        )
    )
    await metrics_repo.save_context_metrics(
        ContextMetrics(
            context_capsule_id=ContextCapsuleId(uuid.uuid4()),
            work_item_id=WorkItemId(uuid.uuid4()),
            execution_id=execution_id,
            context_token_count=1500,
            candidate_count=5,
            selected_entity_count=2,
        )
    )
    await metrics_repo.save_context_outcome(ContextOutcomeSignals(execution_id=execution_id))
    await metrics_repo.save_impact_metrics(
        ImpactAnalysisMetrics(
            execution_id=execution_id,
            predicted_files=["src/a.py"],
            actual_changed_files=["src/a.py"],
        )
    )

    snapshot = await service.reconstruct_execution(execution_id)
    assert snapshot is not None
    assert snapshot.model == "gpt-4o"
    assert snapshot.verification_verdict == "pass"
    assert snapshot.changed_files == ["src/a.py"]
    assert snapshot.context_token_count == 1500


async def test_observability_service_missing_execution_returns_none() -> None:
    metrics_repo = InMemoryMetricsRepository()
    service = ObservabilityService(metrics=metrics_repo, logs=InMemoryLogSink())
    assert await service.reconstruct_execution(ExecutionId(uuid.uuid4())) is None


async def test_record_verification_run_updates_metrics() -> None:
    metrics_repo = InMemoryMetricsRepository()
    service = ObservabilityService(metrics=metrics_repo, logs=InMemoryLogSink())
    execution_id = ExecutionId(uuid.uuid4())
    await metrics_repo.save_execution_metrics(ExecutionMetrics(execution_id=execution_id))
    run = VerificationRun(
        execution_id=execution_id,
        plan=VerificationPlan(
            execution_id=execution_id,
            work_item_id=WorkItemId(uuid.uuid4()),
            steps=[],
        ),
        verdict=VerificationVerdict.FAIL,
        issues=["test relevance missing"],
    )
    await service.record_verification_run(run, execution_id)
    stored = await metrics_repo.get_execution_metrics(execution_id)
    assert stored is not None
    assert stored.verification_outcome == "fail"
    assert stored.duration_seconds is not None
