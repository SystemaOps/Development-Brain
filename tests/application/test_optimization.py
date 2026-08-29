"""Phase 20 application tests: complexity, routing, feedback, test selection."""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.optimization import (
    InMemoryContextFeedbackRepository,
    InMemoryExecutorQualityRepository,
)
from brain.application.optimization import (
    BanditRouter,
    ContextRankingFeedbackService,
    ExecutorQualityTracker,
    ModelRouter,
    TaskComplexityService,
    TestSelectionOptimizer,
)
from brain.domain.identity import ActorId, WorkItemId
from brain.domain.optimization import (
    BanditReward,
    ExecutorQualityEntry,
    RouteTier,
    TaskComplexityInput,
    TaskComplexityLevel,
)


def test_complexity_deterministic_small() -> None:
    service = TaskComplexityService()
    result = service.assess(
        TaskComplexityInput(
            affected_files=1,
            affected_components=0,
            architecture_risk=0.0,
            requirement_ambiguity=0.0,
            estimated_context_size=2000,
        )
    )
    assert result.level == TaskComplexityLevel.DETERMINISTIC
    assert result.score < 0.25


def test_complexity_simple() -> None:
    service = TaskComplexityService()
    result = service.assess(
        TaskComplexityInput(
            affected_files=4,
            architecture_risk=0.1,
            estimated_context_size=10000,
        )
    )
    assert result.level == TaskComplexityLevel.SIMPLE


def test_complexity_medium() -> None:
    service = TaskComplexityService()
    result = service.assess(
        TaskComplexityInput(
            affected_files=6,
            affected_components=2,
            architecture_risk=0.4,
            requirement_ambiguity=0.3,
            estimated_context_size=20000,
        )
    )
    assert result.level == TaskComplexityLevel.MEDIUM


def test_complexity_complex_high_risk() -> None:
    service = TaskComplexityService()
    result = service.assess(
        TaskComplexityInput(
            affected_files=10,
            affected_components=4,
            graph_depth=5,
            architecture_risk=0.9,
            requirement_ambiguity=0.8,
            previous_failures=3,
            estimated_context_size=50000,
        )
    )
    assert result.level == TaskComplexityLevel.COMPLEX


async def test_model_router_routes_by_tier() -> None:
    router = ModelRouter()
    decision = await router.route(
        task_type="simple",
        input=TaskComplexityInput(
            affected_files=1,
            estimated_context_size=1000,
        ),
    )
    assert decision.tier == RouteTier.DETERMINISTIC

    decision = await router.route(
        task_type="medium",
        input=TaskComplexityInput(
            affected_files=8,
            affected_components=3,
            graph_depth=4,
            architecture_risk=0.7,
            requirement_ambiguity=0.5,
            previous_failures=2,
            estimated_context_size=30000,
        ),
    )
    assert decision.tier == RouteTier.LARGE_REASONING
    assert decision.suggested_cost_class == "high"


async def test_model_router_uses_quality_to_boost() -> None:
    quality = InMemoryExecutorQualityRepository()
    router = ModelRouter(quality=quality)
    executor_a = ActorId(uuid.uuid4())
    executor_b = ActorId(uuid.uuid4())
    await quality.save_entry(
        ExecutorQualityEntry(
            executor_id=executor_a, task_type="implementation", successes=9, failures=1
        )
    )
    await quality.save_entry(
        ExecutorQualityEntry(
            executor_id=executor_b, task_type="implementation", successes=1, failures=9
        )
    )
    decision = await router.route(
        task_type="implementation",
        input=TaskComplexityInput(affected_files=2, estimated_context_size=4000),
        available=[executor_a, executor_b],
    )
    assert decision.quality_boosted
    assert "executor" in decision.reason


async def test_context_ranking_feedback_adjusts_weights() -> None:
    repo = InMemoryContextFeedbackRepository()
    service = ContextRankingFeedbackService(feedback=repo)
    work_item_id = WorkItemId(uuid.uuid4())
    adjusted = await service.record_outcome(
        work_item_id=work_item_id,
        execution_id=None,
        outcome="context_missing",
        signal="verifier omitted dependency",
    )
    assert adjusted.retrieval_weight > 1.0
    assert adjusted.graph_distance_weight > 1.0
    assert len(await repo.list_recent(work_item_id)) == 1


async def test_context_ranking_feedback_success_reduces_graph_weight() -> None:
    repo = InMemoryContextFeedbackRepository()
    service = ContextRankingFeedbackService(feedback=repo)
    adjusted = await service.record_outcome(
        work_item_id=WorkItemId(uuid.uuid4()),
        execution_id=None,
        outcome="success",
        signal="clean run",
    )
    assert adjusted.graph_distance_weight < 1.0


def test_test_selection_optimizer_skips_stable_tests() -> None:
    optimizer = TestSelectionOptimizer()
    decisions = optimizer.decide(
        tests=["test_auth", "test_billing", "test_payments"],
        stable_tests=["test_auth", "test_billing"],
        affected_tests={"test_auth"},
        recent_failures=[],
    )
    by_name = {d.test_name: d for d in decisions}
    assert by_name["test_auth"].run is True  # affected -> must run
    assert by_name["test_billing"].run is False  # stable + unaffected
    assert by_name["test_payments"].run is True  # not proven stable
    assert all(d.safety_preserved for d in decisions)


def test_test_selection_optimizer_never_skips_recent_failures() -> None:
    optimizer = TestSelectionOptimizer()
    decisions = optimizer.decide(
        tests=["test_auth"],
        stable_tests=["test_auth"],
        affected_tests=set(),
        recent_failures=["test_auth"],
    )
    assert decisions[0].run is True


async def test_executor_quality_tracker_accumulates() -> None:
    quality = InMemoryExecutorQualityRepository()
    tracker = ExecutorQualityTracker(quality=quality)
    executor_id = ActorId(uuid.uuid4())
    await tracker.record(
        executor_id=executor_id, task_type="bugfix", success=True, tokens=1000, retries=0
    )
    await tracker.record(
        executor_id=executor_id, task_type="bugfix", success=False, tokens=2000, retries=2
    )
    entry = await quality.get_entry(executor_id, "bugfix")
    assert entry is not None
    assert entry.attempts == 2
    assert entry.total_retries == 2
    assert entry.average_tokens == 1500.0


async def test_bandit_router_applies_reward() -> None:
    quality = InMemoryExecutorQualityRepository()
    router = BanditRouter(quality=quality)
    executor_id = ActorId(uuid.uuid4())
    await router.apply_reward(
        BanditReward(
            executor_id=executor_id,
            task_type="feature",
            reward=1.0,
            context_token_count=3000,
            retry_count=1,
            verification_passed=True,
        )
    )
    entry = await quality.get_entry(executor_id, "feature")
    assert entry is not None
    assert entry.successes == 1
    assert entry.total_tokens == 3000
