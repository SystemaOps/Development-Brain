"""Workflow orchestration domain model (Phase 16).

The workflow state contains REFERENCES, not copies of the entire project: it
carries the canonical ids (workflow / project / work item / execution / context
capsule) plus the current stage, retry count, and approval state.  The domain
model is LangGraph-independent; orchestration runs against ports so the domain
stays decoupled from any workflow engine.
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
    VerificationId,
    WorkflowId,
    WorkItemId,
    new_workflow_id,
)


class WorkflowStage(StrEnum):
    INTAKE = "intake"
    UNDERSTAND = "understand"
    BUILD_CONTEXT = "build_context"
    ROUTE_EXECUTOR = "route_executor"
    EXECUTE = "execute"
    VERIFY = "verify"
    RETRY = "retry"
    HUMAN = "human"
    CREATE_PR = "create_pr"
    UPDATE_BRAIN = "update_brain"
    COMPLETE = "complete"
    FAILED = "failed"


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RetryPolicyType(StrEnum):
    """Differentiated retry handling (Task 16.7)."""

    TRANSIENT_TOOL_FAILURE = "transient_tool_failure"
    LLM_FAILURE = "llm_failure"
    VERIFICATION_FAILURE = "verification_failure"
    INVALID_INPUT = "invalid_input"
    HUMAN_REQUIRED = "human_required"


class WorkflowState(BaseModel):
    """Checkpointed workflow state: references, not copies (Task 16.1)."""

    workflow_id: WorkflowId = Field(default_factory=new_workflow_id)
    project_id: ProjectId | None = None
    work_item_id: WorkItemId | None = None
    repository_id: uuid.UUID | None = None
    revision: str | None = None
    current_execution_id: ExecutionId | None = None
    current_context_capsule_id: ContextCapsuleId | None = None
    stage: WorkflowStage = WorkflowStage.INTAKE
    status: WorkflowStatus = WorkflowStatus.RUNNING
    retry_count: int = 0
    max_retries: int = 3
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED
    last_error: str | None = None
    verification_id: VerificationId | None = None
    waiting_for_human: bool = False
    correlation_id: uuid.UUID | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowTransition(BaseModel):
    """One stage transition in the workflow graph."""

    stage: WorkflowStage
    next_stage: WorkflowStage
    condition: str | None = None


class WorkflowEdge(BaseModel):
    """A directed edge in the workflow graph (Task 16.2)."""

    source: WorkflowStage
    target: WorkflowStage
    condition: str | None = None


class WorkflowGraph(BaseModel):
    """Declarative workflow graph definition (Task 16.2)."""

    name: str
    edges: list[WorkflowEdge] = Field(default_factory=list)

    def next_stages(self, stage: WorkflowStage) -> list[WorkflowStage]:
        return [edge.target for edge in self.edges if edge.source == stage]


MAIN_ENGINEERING_GRAPH = WorkflowGraph(
    name="main_engineering",
    edges=[
        WorkflowEdge(source=WorkflowStage.INTAKE, target=WorkflowStage.UNDERSTAND),
        WorkflowEdge(source=WorkflowStage.UNDERSTAND, target=WorkflowStage.BUILD_CONTEXT),
        WorkflowEdge(source=WorkflowStage.BUILD_CONTEXT, target=WorkflowStage.ROUTE_EXECUTOR),
        WorkflowEdge(source=WorkflowStage.ROUTE_EXECUTOR, target=WorkflowStage.EXECUTE),
        WorkflowEdge(source=WorkflowStage.EXECUTE, target=WorkflowStage.VERIFY),
        WorkflowEdge(
            source=WorkflowStage.VERIFY,
            target=WorkflowStage.RETRY,
            condition="verification_failed",
        ),
        WorkflowEdge(
            source=WorkflowStage.VERIFY,
            target=WorkflowStage.HUMAN,
            condition="human_required",
        ),
        WorkflowEdge(
            source=WorkflowStage.VERIFY,
            target=WorkflowStage.CREATE_PR,
            condition="passed",
        ),
        WorkflowEdge(source=WorkflowStage.RETRY, target=WorkflowStage.EXECUTE),
        WorkflowEdge(source=WorkflowStage.CREATE_PR, target=WorkflowStage.UPDATE_BRAIN),
        WorkflowEdge(source=WorkflowStage.UPDATE_BRAIN, target=WorkflowStage.COMPLETE),
    ],
)


PLANNING_GRAPH = WorkflowGraph(
    name="planning",
    edges=[
        WorkflowEdge(source=WorkflowStage.INTAKE, target=WorkflowStage.UNDERSTAND),
        WorkflowEdge(source=WorkflowStage.UNDERSTAND, target=WorkflowStage.BUILD_CONTEXT),
        WorkflowEdge(source=WorkflowStage.BUILD_CONTEXT, target=WorkflowStage.COMPLETE),
    ],
)


__all__ = [
    "ApprovalState",
    "MAIN_ENGINEERING_GRAPH",
    "PLANNING_GRAPH",
    "RetryPolicyType",
    "WorkflowEdge",
    "WorkflowGraph",
    "WorkflowStage",
    "WorkflowState",
    "WorkflowStatus",
    "WorkflowTransition",
]
