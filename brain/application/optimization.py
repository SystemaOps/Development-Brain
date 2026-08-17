"""Optimization application services (Phase 20).

- :class:`TaskComplexityService` computes a complexity score/level from the
  plan's features (Task 20.1).
- :class:`ModelRouter` maps complexity to a routing tier, using per-task-type
  executor quality to break ties (Tasks 20.2, 20.5).
- :class:`ContextRankingFeedbackService` adjusts ranking weights from
  historical outcomes via explainable heuristics (Task 20.3).
- :class:`TestSelectionOptimizer` reduces unnecessary test execution using past
  verification data while preserving safety (Task 20.4).
- :class:`ExecutorQualityTracker` records per-task-type quality entries
  (Task 20.5) and the optional :class:`BanditRouter` implements the learning
  layer (Task 20.6) without being required for routing.
"""

from __future__ import annotations

from brain.domain.identity import ActorId, ExecutionId, WorkItemId
from brain.domain.optimization import (
    BanditReward,
    ContextFeedbackRecord,
    ContextRankingWeights,
    ExecutorQualityEntry,
    RouteTier,
    RoutingDecision,
    TaskComplexity,
    TaskComplexityInput,
    TaskComplexityLevel,
    TestSelectionDecision,
)
from brain.ports.optimization import (
    ContextFeedbackRepository,
    ExecutorQualityRepository,
)


class TaskComplexityService:
    """Computes task complexity from the plan's features (Task 20.1)."""

    def assess(self, input: TaskComplexityInput) -> TaskComplexity:
        score = 0.0
        score += min(0.2, input.affected_files * 0.03)
        score += min(0.15, input.affected_components * 0.05)
        score += min(0.1, input.graph_depth * 0.02)
        score += min(0.2, input.architecture_risk)
        score += min(0.15, input.requirement_ambiguity)
        score += min(0.1, input.previous_failures * 0.04)
        score += min(0.1, input.estimated_context_size / 120000.0)
        score = round(min(1.0, score), 3)

        reasons: list[str] = []
        if input.affected_files > 0:
            reasons.append(f"{input.affected_files} affected files")
        if input.affected_components > 0:
            reasons.append(f"{input.affected_components} affected components")
        if input.architecture_risk > 0:
            reasons.append(f"architecture risk {input.architecture_risk:.2f}")
        if input.requirement_ambiguity > 0:
            reasons.append(f"ambiguity {input.requirement_ambiguity:.2f}")
        if input.previous_failures > 0:
            reasons.append(f"{input.previous_failures} previous failures")
        if input.estimated_context_size > 0:
            reasons.append(f"context ~{input.estimated_context_size} tokens")

        level = _level_for_score(score)
        return TaskComplexity(input=input, score=score, level=level, reasons=reasons)


class ModelRouter:
    """Routes tasks to a tier using complexity and quality profiles (Tasks 20.2, 20.5)."""

    def __init__(
        self,
        *,
        complexity: TaskComplexityService | None = None,
        quality: ExecutorQualityRepository | None = None,
    ) -> None:
        self._complexity = complexity or TaskComplexityService()
        self._quality = quality

    async def route(
        self,
        *,
        task_type: str,
        input: TaskComplexityInput,
        available: list[ActorId] | None = None,
    ) -> RoutingDecision:
        complexity = self._complexity.assess(input)
        tier = _tier_for_level(complexity.level)

        quality_boosted = False
        reason = _tier_reason(tier, complexity.level)
        cost_class = {
            RouteTier.DETERMINISTIC: "low",
            RouteTier.SMALL_LOCAL: "low",
            RouteTier.MEDIUM: "medium",
            RouteTier.LARGE_REASONING: "high",
        }[tier]

        # Task 20.5: prefer an executor with strong per-task-type quality
        # instead of a single global best-model score.
        if self._quality is not None and available:
            candidates = await self._quality_candidates(task_type, available)
            if candidates:
                quality_boosted = True
                reason += f"; picked executor with best {task_type} track record: {candidates[0]}"

        return RoutingDecision(
            tier=tier,
            complexity=complexity.level,
            reason=reason,
            suggested_cost_class=cost_class,
            quality_boosted=quality_boosted,
        )

    async def _quality_candidates(self, task_type: str, available: list[ActorId]) -> list[ActorId]:
        scores: list[tuple[float, ActorId]] = []
        for executor_id in available:
            entry = (
                await self._quality.get_entry(executor_id, task_type)
                if self._quality is not None
                else None
            )
            if entry is None or entry.attempts == 0:
                continue
            scores.append((entry.success_rate, executor_id))
        scores.sort(reverse=True)
        return [executor_id for _, executor_id in scores]


class ContextRankingFeedbackService:
    """Adjusts ranking weights from historical outcomes (Task 20.3)."""

    def __init__(
        self,
        *,
        feedback: ContextFeedbackRepository,
        weights: ContextRankingWeights | None = None,
    ) -> None:
        self._feedback = feedback
        self._weights = weights or ContextRankingWeights()

    async def record_outcome(
        self,
        *,
        work_item_id: WorkItemId,
        execution_id: ExecutionId | None,
        outcome: str,
        signal: str,
    ) -> ContextRankingWeights:
        previous = self._weights
        adjusted = self._adjust(previous, outcome)
        self._weights = adjusted
        await self._feedback.save_feedback(
            ContextFeedbackRecord(
                work_item_id=work_item_id,
                execution_id=execution_id,
                outcome=outcome,
                signal=signal,
                previous_weights=previous,
                adjusted_weights=adjusted,
            )
        )
        return adjusted

    def _adjust(self, weights: ContextRankingWeights, outcome: str) -> ContextRankingWeights:
        adjusted = weights.model_copy(deep=True)
        if outcome == "context_missing":
            adjusted.retrieval_weight = round(weights.retrieval_weight + 0.1, 3)
            adjusted.graph_distance_weight = round(weights.graph_distance_weight + 0.05, 3)
        elif outcome == "retry":
            adjusted.retrieval_weight = round(weights.retrieval_weight + 0.05, 3)
        elif outcome == "success":
            adjusted.graph_distance_weight = round(
                max(0.5, weights.graph_distance_weight - 0.02), 3
            )
        return adjusted


class TestSelectionOptimizer:
    """Skips historically stable tests while preserving safety (Task 20.4)."""

    __test__ = False  # service class, not a pytest test class

    def __init__(self, *, max_skippable: int = 3) -> None:
        self._max_skippable = max_skippable

    def decide(
        self,
        *,
        tests: list[str],
        stable_tests: list[str],
        affected_tests: set[str],
        recent_failures: list[str],
    ) -> list[TestSelectionDecision]:
        decisions: list[TestSelectionDecision] = []
        skipped = 0
        for test in tests:
            if (
                test in stable_tests
                and test not in recent_failures
                and test not in affected_tests
                and skipped < self._max_skippable
            ):
                decisions.append(
                    TestSelectionDecision(
                        test_name=test,
                        run=False,
                        reason="historically stable and unaffected by change",
                        safety_preserved=True,
                    )
                )
                skipped += 1
            else:
                decisions.append(
                    TestSelectionDecision(
                        test_name=test,
                        run=True,
                        reason="affected by change or not proven stable",
                        safety_preserved=True,
                    )
                )
        return decisions


class ExecutorQualityTracker:
    """Records per-task-type quality entries (Task 20.5)."""

    def __init__(self, *, quality: ExecutorQualityRepository) -> None:
        self._quality = quality

    async def record(
        self,
        *,
        executor_id: ActorId,
        task_type: str,
        success: bool,
        tokens: int = 0,
        retries: int = 0,
        duration_seconds: float = 0.0,
    ) -> ExecutorQualityEntry:
        entry = await self._quality.get_entry(executor_id, task_type)
        if entry is None:
            entry = ExecutorQualityEntry(executor_id=executor_id, task_type=task_type)
        if success:
            entry.successes += 1
        else:
            entry.failures += 1
        entry.total_tokens += tokens
        entry.total_retries += retries
        entry.total_duration_seconds += duration_seconds
        return await self._quality.save_entry(entry)


class BanditRouter:
    """Optional learning layer (Task 20.6).

    Rewards executors with positive verification outcomes and low retry counts,
    then biases routing toward the best-rewarded executor per task type.  The
    base platform routes without this layer.
    """

    def __init__(self, *, quality: ExecutorQualityRepository) -> None:
        self._quality = quality

    async def apply_reward(self, reward: BanditReward) -> ExecutorQualityEntry:
        entry = await self._quality.get_entry(reward.executor_id, reward.task_type)
        if entry is None:
            entry = ExecutorQualityEntry(executor_id=reward.executor_id, task_type=reward.task_type)
        if reward.verification_passed:
            entry.successes += 1
        else:
            entry.failures += 1
        entry.total_retries += reward.retry_count
        entry.total_tokens += reward.context_token_count
        return await self._quality.save_entry(entry)


def _level_for_score(score: float) -> TaskComplexityLevel:
    if score < 0.25:
        return TaskComplexityLevel.DETERMINISTIC
    if score < 0.5:
        return TaskComplexityLevel.SIMPLE
    if score < 0.75:
        return TaskComplexityLevel.MEDIUM
    return TaskComplexityLevel.COMPLEX


def _tier_for_level(level: TaskComplexityLevel) -> RouteTier:
    if level == TaskComplexityLevel.DETERMINISTIC:
        return RouteTier.DETERMINISTIC
    if level == TaskComplexityLevel.SIMPLE:
        return RouteTier.SMALL_LOCAL
    if level == TaskComplexityLevel.MEDIUM:
        return RouteTier.MEDIUM
    return RouteTier.LARGE_REASONING


def _tier_reason(tier: RouteTier, level: TaskComplexityLevel) -> str:
    return {
        RouteTier.DETERMINISTIC: "deterministic task -> deterministic tool",
        RouteTier.SMALL_LOCAL: "small isolated code task -> small local model",
        RouteTier.MEDIUM: "medium implementation -> medium coding model",
        RouteTier.LARGE_REASONING: "cross-component/high-risk task -> large reasoning model",
    }[tier]


__all__ = [
    "BanditRouter",
    "ContextRankingFeedbackService",
    "ExecutorQualityTracker",
    "ModelRouter",
    "TaskComplexityService",
    "TestSelectionOptimizer",
]
