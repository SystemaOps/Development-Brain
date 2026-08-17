"""Observability, metrics, and context-quality domain model (Phase 18).

The brain must measure whether it actually improves software-engineering
execution.  This module defines:

- :class:`LogContext` / :class:`LogEntry` — structured logging where every
  entry carries the available ids (project / workflow / work item / execution /
  correlation) so an operational chain can be reconstructed (Task 18.1).
- :class:`ExecutionMetrics` — duration, model, tokens, tool calls, commands,
  retries, verification outcome (Task 18.2).
- :class:`ContextMetrics` — context token count, candidate/selected counts,
  retrieval-source distribution, JIT requests, and explainable selected context
  (Task 18.3).
- :class:`ContextOutcomeSignals` — signals about context quality such as a
  missing file discovered later or a verifier-omitted dependency (Task 18.4).
- :class:`ImpactAnalysisMetrics` — predicted vs actual changed files, false
  positives and false negatives (Task 18.5).
- :class:`MetricsSnapshot` — the completion-gate reconstruction of one
  execution: context selected, why, model, changes, and verification verdict.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ContextCapsuleId,
    ExecutionId,
    ProjectId,
    WorkItemId,
)


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogContext(BaseModel):
    """Identifiers attached to every structured log entry (Task 18.1)."""

    project_id: ProjectId | None = None
    workflow_id: uuid.UUID | None = None
    work_item_id: WorkItemId | None = None
    execution_id: ExecutionId | None = None
    correlation_id: uuid.UUID | None = None


class LogEntry(BaseModel):
    """One structured log event."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    level: LogLevel
    event: str
    message: str
    context: LogContext = Field(default_factory=LogContext)
    payload: dict[str, object] = Field(default_factory=dict)


class ExecutionMetrics(BaseModel):
    """Per-execution operational metrics (Task 18.2)."""

    execution_id: ExecutionId
    workflow_id: uuid.UUID | None = None
    work_item_id: WorkItemId | None = None
    project_id: ProjectId | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: int = 0
    commands_executed: list[str] = Field(default_factory=list)
    retries: int = 0
    verification_outcome: str | None = None


class SelectedContextItem(BaseModel):
    """Why one context item was selected (Task 10.8 / 18.3)."""

    entity_type: str
    entity_id: uuid.UUID
    reason: str
    retrieval_source: str
    relevance_score: float = 0.0


class ContextMetrics(BaseModel):
    """Per-capsule context metrics (Task 18.3)."""

    context_capsule_id: ContextCapsuleId
    work_item_id: WorkItemId
    execution_id: ExecutionId | None = None
    context_token_count: int = 0
    candidate_count: int = 0
    selected_entity_count: int = 0
    retrieval_source_distribution: dict[str, int] = Field(default_factory=dict)
    jit_retrieval_requests: int = 0
    selected_context: list[SelectedContextItem] = Field(default_factory=list)


class ContextOutcomeSignals(BaseModel):
    """Context-quality outcome signals (Task 18.4)."""

    execution_id: ExecutionId
    missing_files_discovered_later: list[str] = Field(default_factory=list)
    verifier_omitted_dependencies: list[str] = Field(default_factory=list)
    additional_context_requests: int = 0
    irrelevant_context_rate: float = 0.0
    retry_caused_by_context_failure: bool = False


class ImpactAnalysisMetrics(BaseModel):
    """Predicted vs actual impact (Task 18.5)."""

    execution_id: ExecutionId
    predicted_files: list[str] = Field(default_factory=list)
    actual_changed_files: list[str] = Field(default_factory=list)

    @property
    def false_positives(self) -> list[str]:
        """Predicted as affected but not actually changed."""
        return sorted(set(self.predicted_files) - set(self.actual_changed_files))

    @property
    def false_negatives(self) -> list[str]:
        """Actually changed but not predicted as affected."""
        return sorted(set(self.actual_changed_files) - set(self.predicted_files))


class MetricsSnapshot(BaseModel):
    """Reconstructs one execution for a developer (Phase 18 gate)."""

    execution_id: ExecutionId
    workflow_id: uuid.UUID | None = None
    work_item_id: WorkItemId | None = None
    project_id: ProjectId | None = None
    model: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    verification_verdict: str | None = None
    verification_reasons: list[str] = Field(default_factory=list)
    selected_context: list[SelectedContextItem] = Field(default_factory=list)
    context_token_count: int = 0
    execution: ExecutionMetrics | None = None
    context: ContextMetrics | None = None
    outcome: ContextOutcomeSignals | None = None
    impact: ImpactAnalysisMetrics | None = None


__all__ = [
    "ContextMetrics",
    "ContextOutcomeSignals",
    "ExecutionMetrics",
    "ImpactAnalysisMetrics",
    "LogContext",
    "LogEntry",
    "LogLevel",
    "MetricsSnapshot",
    "SelectedContextItem",
]
