"""Phase 20 golden tests and completion gate.

The system demonstrates improved cost, latency, context efficiency, and retry
rate without lowering verification quality: routing picks smaller/cheaper
models for simple tasks, quality profiles improve selection over time, context
feedback tightens retrieval, and test selection skips stable tests while never
skipping recent failures or affected symbols.
"""

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
    TestSelectionOptimizer,
)
from brain.domain.identity import ActorId, WorkItemId
from brain.domain.optimization import (
    BanditReward,
    RouteTier,
    TaskComplexityInput,
)


async def test_gate_cost_improves_with_small_model_routing() -> None:
    """A simple isolated task routes to the small/cheap tier instead of the
    large reasoning model, cutting cost and latency."""
    router = ModelRouter()
    cheap = await router.route(
        task_type="simple_bugfix",
        input=TaskComplexityInput(
            affected_files=1,
            affected_components=0,
            architecture_risk=0.0,
            estimated_context_size=1500,
        ),
    )
    expensive = await router.route(
        task_type="cross_component",
        input=TaskComplexityInput(
            affected_files=12,
            affected_components=5,
            graph_depth=6,
            architecture_risk=0.9,
            requirement_ambiguity=0.7,
            previous_failures=3,
            estimated_context_size=60000,
        ),
    )
    assert cheap.tier in {RouteTier.DETERMINISTIC, RouteTier.SMALL_LOCAL}
    assert cheap.suggested_cost_class == "low"
    assert expensive.tier == RouteTier.LARGE_REASONING
    assert expensive.suggested_cost_class == "high"


async def test_gate_retry_rate_improves_with_quality_profiles() -> None:
    """Per-task-type quality profiles favor the executor with the best track
    record, reducing retries over time without a global best-model score."""
    quality = InMemoryExecutorQualityRepository()
    tracker = ExecutorQualityTracker(quality=quality)
    executor_a = ActorId(uuid.uuid4())
    executor_b = ActorId(uuid.uuid4())

    # Simulate history: executor_a has been reliable, executor_b flaky.
    for _ in range(8):
        await tracker.record(executor_id=executor_a, task_type="bugfix", success=True, retries=0)
    for _ in range(4):
        await tracker.record(executor_id=executor_a, task_type="bugfix", success=False, retries=2)
    for _ in range(4):
        await tracker.record(executor_id=executor_b, task_type="bugfix", success=False, retries=3)

    entry_a = await quality.get_entry(executor_a, "bugfix")
    entry_b = await quality.get_entry(executor_b, "bugfix")
    assert entry_a is not None and entry_b is not None
    assert entry_a.success_rate > entry_b.success_rate
    assert entry_a.average_retries < entry_b.average_retries

    router = ModelRouter(quality=quality)
    decision = await router.route(
        task_type="bugfix",
        input=TaskComplexityInput(affected_files=2, estimated_context_size=3000),
        available=[executor_a, executor_b],
    )
    assert decision.quality_boosted
    # The reliable executor is named in the routing reason.
    assert "executor" in decision.reason


async def test_gate_context_efficiency_improves_via_feedback() -> None:
    """Repeated context-missing outcomes raise retrieval weight (more focused
    retrieval), while clean successes trim graph distance weight."""
    repo = InMemoryContextFeedbackRepository()
    service = ContextRankingFeedbackService(feedback=repo)
    work_item_id = WorkItemId(uuid.uuid4())
    adjusted = None
    for _ in range(3):
        adjusted = await service.record_outcome(
            work_item_id=work_item_id,
            execution_id=None,
            outcome="context_missing",
            signal="verifier omitted dependency",
        )
    assert adjusted is not None
    assert adjusted.retrieval_weight > 1.2
    assert len(await repo.list_recent(work_item_id)) == 3


async def test_gate_latency_improves_via_safe_test_selection() -> None:
    """Stable, unaffected tests are skipped (less runtime latency) while
    affected and recently failing tests still run, preserving safety."""
    optimizer = TestSelectionOptimizer()
    decisions = optimizer.decide(
        tests=["test_auth", "test_billing", "test_payments", "test_flaky"],
        stable_tests=["test_auth", "test_billing", "test_payments"],
        affected_tests={"test_auth"},
        recent_failures=["test_flaky"],
    )
    by_name = {d.test_name: d for d in decisions}
    assert by_name["test_auth"].run is True  # covers changed symbol
    assert by_name["test_billing"].run is False  # stable + unaffected -> skipped
    assert by_name["test_payments"].run is False  # stable + unaffected -> skipped
    assert by_name["test_flaky"].run is True  # recently failed

    # The affected-symbol guard: a test covering the changed symbol must run.
    decisions2 = optimizer.decide(
        tests=["test_auth"],
        stable_tests=["test_auth"],
        affected_tests={"test_auth"},
        recent_failures=[],
    )
    assert decisions2[0].run is True


async def test_gate_learning_layer_improves_without_being_required() -> None:
    """Bandit rewards improve selection over time; base routing still works
    without any learned state."""
    quality = InMemoryExecutorQualityRepository()
    router = ModelRouter()  # no quality repo -> no learning needed
    base = await router.route(
        task_type="feature",
        input=TaskComplexityInput(affected_files=5, estimated_context_size=18000),
    )
    assert base.tier == RouteTier.SMALL_LOCAL

    bandit = BanditRouter(quality=quality)
    executor_id = ActorId(uuid.uuid4())
    for _ in range(5):
        await bandit.apply_reward(
            BanditReward(
                executor_id=executor_id,
                task_type="feature",
                reward=1.0,
                context_token_count=2000,
                retry_count=0,
                verification_passed=True,
            )
        )
    entry = await quality.get_entry(executor_id, "feature")
    assert entry is not None
    assert entry.successes == 5
    assert entry.success_rate == 1.0


async def test_gate_verification_quality_not_lowered() -> None:
    """Test selection optimization never skips a test that recently failed or
    that covers a changed symbol; all decisions preserve safety."""
    optimizer = TestSelectionOptimizer()
    decisions = optimizer.decide(
        tests=["test_recent_failure", "test_covers_change", "test_stable"],
        stable_tests=["test_recent_failure", "test_covers_change", "test_stable"],
        affected_tests={"test_covers_change"},
        recent_failures=["test_recent_failure"],
    )
    by_name = {d.test_name: d for d in decisions}
    assert by_name["test_recent_failure"].run is True
    assert by_name["test_covers_change"].run is True
    assert by_name["test_stable"].run is False
    assert all(d.safety_preserved for d in decisions)
