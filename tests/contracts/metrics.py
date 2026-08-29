"""MetricsRepository contract (Phase 18)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import ContextCapsuleId, ExecutionId, WorkItemId
from brain.domain.observability import (
    ContextMetrics,
    ContextOutcomeSignals,
    ExecutionMetrics,
    ImpactAnalysisMetrics,
    SelectedContextItem,
)
from brain.ports.observability import MetricsRepository


def _execution_metrics() -> ExecutionMetrics:
    return ExecutionMetrics(
        execution_id=ExecutionId(uuid.uuid4()),
        workflow_id=uuid.uuid4(),
        work_item_id=WorkItemId(uuid.uuid4()),
        model="gpt-4o",
        tokens_in=120,
        tokens_out=340,
        tool_calls=5,
        commands_executed=["pytest", "ruff"],
        retries=1,
        verification_outcome="pass",
        duration_seconds=12.5,
    )


class MetricsRepositoryContract:
    @pytest.fixture
    def metrics(self) -> MetricsRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, metrics: MetricsRepository) -> None:
        assert isinstance(metrics, MetricsRepository)

    async def test_execution_metrics_round_trip(self, metrics: MetricsRepository) -> None:
        record = _execution_metrics()
        await metrics.save_execution_metrics(record)
        stored = await metrics.get_execution_metrics(record.execution_id)
        assert stored is not None
        assert stored.model == "gpt-4o"
        assert stored.tokens_in == 120
        assert stored.tokens_out == 340
        assert stored.tool_calls == 5
        assert stored.retries == 1
        assert stored.verification_outcome == "pass"
        assert stored.commands_executed == ["pytest", "ruff"]
        assert stored.duration_seconds == 12.5

    async def test_execution_metrics_missing_returns_none(self, metrics: MetricsRepository) -> None:
        assert await metrics.get_execution_metrics(ExecutionId(uuid.uuid4())) is None

    async def test_execution_metrics_upsert(self, metrics: MetricsRepository) -> None:
        record = _execution_metrics()
        await metrics.save_execution_metrics(record)
        record.tokens_out = 999
        await metrics.save_execution_metrics(record)
        stored = await metrics.get_execution_metrics(record.execution_id)
        assert stored is not None
        assert stored.tokens_out == 999

    async def test_context_metrics_round_trip(self, metrics: MetricsRepository) -> None:
        execution_id = ExecutionId(uuid.uuid4())
        record = ContextMetrics(
            context_capsule_id=ContextCapsuleId(uuid.uuid4()),
            work_item_id=WorkItemId(uuid.uuid4()),
            execution_id=execution_id,
            context_token_count=4000,
            candidate_count=25,
            selected_entity_count=8,
            retrieval_source_distribution={"code_graph": 5, "requirement": 3},
            jit_retrieval_requests=2,
            selected_context=[
                SelectedContextItem(
                    entity_type="Symbol",
                    entity_id=uuid.uuid4(),
                    reason="contains primary impacted symbol",
                    retrieval_source="code_graph",
                    relevance_score=0.9,
                )
            ],
        )
        await metrics.save_context_metrics(record)
        stored = await metrics.get_context_metrics(execution_id)
        assert stored is not None
        assert stored.context_token_count == 4000
        assert stored.candidate_count == 25
        assert stored.selected_entity_count == 8
        assert stored.retrieval_source_distribution == {"code_graph": 5, "requirement": 3}
        assert stored.jit_retrieval_requests == 2
        assert stored.selected_context[0].reason == "contains primary impacted symbol"

    async def test_context_metrics_missing_returns_none(self, metrics: MetricsRepository) -> None:
        assert await metrics.get_context_metrics(ExecutionId(uuid.uuid4())) is None

    async def test_context_outcome_round_trip(self, metrics: MetricsRepository) -> None:
        execution_id = ExecutionId(uuid.uuid4())
        signals = ContextOutcomeSignals(
            execution_id=execution_id,
            missing_files_discovered_later=["src/omitted.py"],
            verifier_omitted_dependencies=["src/omitted.py"],
            additional_context_requests=3,
            irrelevant_context_rate=0.2,
            retry_caused_by_context_failure=True,
        )
        await metrics.save_context_outcome(signals)
        stored = await metrics.get_context_outcome(execution_id)
        assert stored is not None
        assert stored.missing_files_discovered_later == ["src/omitted.py"]
        assert stored.additional_context_requests == 3
        assert stored.irrelevant_context_rate == 0.2
        assert stored.retry_caused_by_context_failure is True

    async def test_context_outcome_missing_returns_none(self, metrics: MetricsRepository) -> None:
        assert await metrics.get_context_outcome(ExecutionId(uuid.uuid4())) is None

    async def test_impact_metrics_round_trip(self, metrics: MetricsRepository) -> None:
        execution_id = ExecutionId(uuid.uuid4())
        record = ImpactAnalysisMetrics(
            execution_id=execution_id,
            predicted_files=["src/a.py", "src/b.py"],
            actual_changed_files=["src/a.py", "src/c.py"],
        )
        await metrics.save_impact_metrics(record)
        stored = await metrics.get_impact_metrics(execution_id)
        assert stored is not None
        assert stored.predicted_files == ["src/a.py", "src/b.py"]
        assert stored.actual_changed_files == ["src/a.py", "src/c.py"]
        assert stored.false_positives == ["src/b.py"]
        assert stored.false_negatives == ["src/c.py"]

    async def test_impact_metrics_missing_returns_none(self, metrics: MetricsRepository) -> None:
        assert await metrics.get_impact_metrics(ExecutionId(uuid.uuid4())) is None
