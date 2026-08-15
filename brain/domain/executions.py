"""Execution domain.

An Execution is ONE attempt to perform work.  Multiple executions may exist
for a single work item (implementation failed, tests failed, verification
passed).  Previous attempts are never overwritten.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ActorId,
    ArtifactId,
    ContextCapsuleId,
    EvidenceId,
    ExecutionId,
    WorkflowId,
    WorkItemId,
    new_execution_id,
)


class ExecutionStatus(StrEnum):
    REQUESTED = "requested"
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class Execution(BaseModel):
    id: ExecutionId = Field(default_factory=new_execution_id)
    workflow_id: WorkflowId
    work_item_id: WorkItemId
    executor_id: ActorId
    context_capsule_id: ContextCapsuleId | None = None
    status: ExecutionStatus = ExecutionStatus.REQUESTED
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    parent_execution_id: ExecutionId | None = None
    correlation_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class ExecutionPermissions(BaseModel):
    """Capability policy enforced by the executor runtime."""

    repository_read: bool = True
    repository_write: bool = False
    shell: bool = False
    network: bool = False
    git_commit: bool = False
    git_push: bool = False
    create_pull_request: bool = False
    merge_pull_request: bool = False
    run_containers: bool = False
    access_secrets: bool = False
    deploy: bool = False


class ExecutionRequest(BaseModel):
    """What the brain hands to any executor behind ``ExecutorPort``."""

    execution_id: ExecutionId
    workflow_id: WorkflowId
    work_item_id: WorkItemId
    repository_ref: str
    base_revision: str
    workspace_path: str | None = None
    context_capsule_id: ContextCapsuleId | None = None
    permissions: ExecutionPermissions = Field(default_factory=ExecutionPermissions)
    correlation_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class ExecutionResult(BaseModel):
    """Structured result an executor returns to the brain."""

    execution_id: ExecutionId
    status: ExecutionStatus
    modified_files: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    commands_executed: list[str] = Field(default_factory=list)
    tests_executed: list[str] = Field(default_factory=list)
    diff: str | None = None
    artifact_refs: list[ArtifactId] = Field(default_factory=list)
    evidence_refs: list[EvidenceId] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
