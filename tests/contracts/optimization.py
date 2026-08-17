"""Optimization repositories contract (Phase 20)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import ActorId, WorkItemId
from brain.domain.optimization import (
    ContextFeedbackRecord,
    ContextRankingWeights,
    ExecutorQualityEntry,
)
from brain.ports.optimization import (
    ContextFeedbackRepository,
    ExecutorQualityRepository,
)


class ExecutorQualityRepositoryContract:
    @pytest.fixture
    def quality(self) -> ExecutorQualityRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, quality: ExecutorQualityRepository) -> None:
        assert isinstance(quality, ExecutorQualityRepository)

    async def test_save_and_get_entry(self, quality: ExecutorQualityRepository) -> None:
        executor_id = ActorId(uuid.uuid4())
        entry = ExecutorQualityEntry(
            executor_id=executor_id,
            task_type="medium_implementation",
            successes=4,
            failures=1,
            total_tokens=50000,
            total_retries=2,
            total_duration_seconds=120.0,
        )
        await quality.save_entry(entry)
        stored = await quality.get_entry(executor_id, "medium_implementation")
        assert stored is not None
        assert stored.success_rate == 0.8
        assert stored.average_retries == 0.4
        assert stored.average_tokens == 10000.0

    async def test_upsert_updates_entry(self, quality: ExecutorQualityRepository) -> None:
        executor_id = ActorId(uuid.uuid4())
        entry = ExecutorQualityEntry(executor_id=executor_id, task_type="simple")
        await quality.save_entry(entry)
        entry.successes = 2
        entry.failures = 1
        await quality.save_entry(entry)
        stored = await quality.get_entry(executor_id, "simple")
        assert stored is not None
        assert stored.attempts == 3
        assert stored.success_rate == round(2 / 3, 3)

    async def test_list_for_executor(self, quality: ExecutorQualityRepository) -> None:
        executor_id = ActorId(uuid.uuid4())
        await quality.save_entry(
            ExecutorQualityEntry(executor_id=executor_id, task_type="a", successes=1)
        )
        await quality.save_entry(
            ExecutorQualityEntry(executor_id=executor_id, task_type="b", successes=1)
        )
        assert len(await quality.list_for_executor(executor_id)) == 2

    async def test_list_by_task_type(self, quality: ExecutorQualityRepository) -> None:
        await quality.save_entry(
            ExecutorQualityEntry(executor_id=ActorId(uuid.uuid4()), task_type="x", successes=1)
        )
        await quality.save_entry(
            ExecutorQualityEntry(executor_id=ActorId(uuid.uuid4()), task_type="x", successes=1)
        )
        assert len(await quality.list_by_task_type("x")) == 2


class ContextFeedbackRepositoryContract:
    @pytest.fixture
    def feedback(self) -> ContextFeedbackRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, feedback: ContextFeedbackRepository) -> None:
        assert isinstance(feedback, ContextFeedbackRepository)

    async def test_save_and_list_recent(self, feedback: ContextFeedbackRepository) -> None:
        record = ContextFeedbackRecord(
            work_item_id=WorkItemId(uuid.uuid4()),
            outcome="context_missing",
            signal="verifier omitted dependency",
            previous_weights=ContextRankingWeights(),
            adjusted_weights=ContextRankingWeights(retrieval_weight=1.1),
        )
        await feedback.save_feedback(record)
        listed = await feedback.list_recent(record.work_item_id)
        assert [r.id for r in listed] == [record.id]
        assert listed[0].adjusted_weights.retrieval_weight == 1.1

    async def test_list_recent_filters_by_work_item(
        self, feedback: ContextFeedbackRepository
    ) -> None:
        other = WorkItemId(uuid.uuid4())
        await feedback.save_feedback(
            ContextFeedbackRecord(
                work_item_id=other,
                outcome="success",
                signal="ok",
            )
        )
        assert await feedback.list_recent(WorkItemId(uuid.uuid4())) == []
