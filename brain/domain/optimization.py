"""Optimization, model routing, and learning domain model (Phase 20).

Improves cost, latency, context quality, and model selection after the core
system is correct.  A :class:`TaskComplexityInput` gathers the plan's features
(Task 20.1); :class:`ModelRouter` maps complexity to a routing tier
(Task 20.2); :class:`ContextRankingWeights` captures feedback-adjusted weights
(Task 20.3); :class:`TestSelectionDecision` captures safe test-execution
optimization (Task 20.4); :class:`ExecutorQualityEntry` tracks per-task-type
quality instead of one global "best model" score (Task 20.5).  The learning
layer (bandit routing, reward weighting, Task 20.6) is optional: the base
platform routes without it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import ActorId, ExecutionId, WorkItemId


class TaskComplexityLevel(StrEnum):
    DETERMINISTIC = "deterministic"
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class RouteTier(StrEnum):
    DETERMINISTIC = "deterministic"
    SMALL_LOCAL = "small_local"
    MEDIUM = "medium"
    LARGE_REASONING = "large_reasoning"


class TaskComplexityInput(BaseModel):
    """Features for the task complexity model (Task 20.1)."""

    affected_files: int = 0
    affected_components: int = 0
    graph_depth: int = 0
    architecture_risk: float = 0.0
    requirement_ambiguity: float = 0.0
    previous_failures: int = 0
    estimated_context_size: int = 0


class TaskComplexity(BaseModel):
    """Computed complexity score and level."""

    input: TaskComplexityInput
    score: float = 0.0
    level: TaskComplexityLevel = TaskComplexityLevel.DETERMINISTIC
    reasons: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    """The model router's choice (Task 20.2)."""

    tier: RouteTier
    complexity: TaskComplexityLevel
    reason: str
    suggested_cost_class: str = "low"
    quality_boosted: bool = False


class ContextRankingWeights(BaseModel):
    """Feedback-adjusted ranking weights (Task 20.3)."""

    retrieval_weight: float = 1.0
    graph_distance_weight: float = 1.0
    entity_priorities: dict[str, float] = Field(default_factory=dict)
    token_allocation: dict[str, float] = Field(default_factory=dict)


class ContextFeedbackRecord(BaseModel):
    """One feedback signal used to adjust ranking weights (Task 20.3)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    work_item_id: WorkItemId
    execution_id: ExecutionId | None = None
    outcome: str  # success / retry / context_missing
    signal: str
    previous_weights: ContextRankingWeights = Field(default_factory=ContextRankingWeights)
    adjusted_weights: ContextRankingWeights = Field(default_factory=ContextRankingWeights)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TestSelectionDecision(BaseModel):
    """Whether one test should run in the targeted set (Task 20.4)."""

    test_name: str
    run: bool
    reason: str
    safety_preserved: bool = True


class ExecutorQualityEntry(BaseModel):
    """Per-task-type quality tracking for one executor (Task 20.5)."""

    executor_id: ActorId
    task_type: str
    successes: int = 0
    failures: int = 0
    total_tokens: int = 0
    total_retries: int = 0
    total_duration_seconds: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def attempts(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return round(self.successes / self.attempts, 3)

    @property
    def average_retries(self) -> float:
        if self.attempts == 0:
            return 0.0
        return round(self.total_retries / self.attempts, 3)

    @property
    def average_tokens(self) -> float:
        if self.attempts == 0:
            return 0.0
        return round(self.total_tokens / self.attempts, 1)


class BanditReward(BaseModel):
    """Reward signal for the optional learning layer (Task 20.6)."""

    executor_id: ActorId
    task_type: str
    reward: float
    context_token_count: int = 0
    retry_count: int = 0
    verification_passed: bool = True


__all__ = [
    "BanditReward",
    "ContextFeedbackRecord",
    "ContextRankingWeights",
    "ExecutorQualityEntry",
    "RouteTier",
    "RoutingDecision",
    "TaskComplexity",
    "TaskComplexityInput",
    "TaskComplexityLevel",
    "TestSelectionDecision",
]
