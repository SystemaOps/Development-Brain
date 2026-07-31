from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.evidence import EvidenceRef


class AgentRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING = "waiting"
    CANCELLED = "cancelled"


class AgentNextAction(StrEnum):
    NONE = "none"
    REQUEST_APPROVAL = "request_approval"
    REQUEST_CLARIFICATION = "request_clarification"
    RUN_PLANNING = "run_planning"
    RUN_CODING = "run_coding"
    RUN_VERIFICATION = "run_verification"
    COMPLETE = "complete"
    ESCALATE = "escalate"
    RETRY = "retry"


class AgentErrorCategory(StrEnum):
    VALIDATION_ERROR = "validation_error"
    CONFIGURATION_ERROR = "configuration_error"
    DEPENDENCY_ERROR = "dependency_error"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    CHECKPOINT_ERROR = "checkpoint_error"
    REPOSITORY_ERROR = "repository_error"
    LLM_ERROR = "llm_error"
    BLOCKED_ERROR = "blocked_error"
    RETRYABLE_ERROR = "retryable_error"
    NON_RETRYABLE_ERROR = "non_retryable_error"


class ArtifactReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str
    artifact_type: str
    uri: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    namespace: str
    key: str
    checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentError(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: AgentErrorCategory
    message: str
    retryable: bool = False
    code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(BaseModel):
    execution_id: UUID = Field(default_factory=uuid4)
    project_id: str
    task_id: str | None = None
    agent_type: str
    objective: str
    input_artifacts: list[ArtifactReference] = Field(default_factory=list)
    state: StateReference | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    execution_id: UUID
    project_id: str | None = None
    task_id: str | None = None
    agent_type: str
    status: AgentRunStatus
    summary: str
    output_artifacts: list[ArtifactReference] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    state: StateReference | None = None
    next_action: AgentNextAction = AgentNextAction.NONE
    errors: list[AgentError] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
