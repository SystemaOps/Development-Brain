"""Command envelope and canonical commands (Phase 24).

Long-running work is expressed as canonical :class:`CommandEnvelope` messages
so the orchestration path does not depend on the trigger source (user, event,
scheduled, internal).  Every command carries ids for correlation and
traceability; handlers converge on the same application services.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ActorId,
    ExecutionId,
    ProjectId,
    RepositoryId,
    WorkItemId,
)


class TriggerType(StrEnum):
    USER = "user"
    EVENT = "event"
    SCHEDULED = "scheduled"
    INTERNAL = "internal"


class CommandType(StrEnum):
    ANALYZE_PROJECT = "analyze_project"
    SYNC_REPOSITORY = "sync_repository"
    INGEST_REPOSITORY = "ingest_repository"
    INGEST_DOCUMENT = "ingest_document"
    EXTRACT_REQUIREMENTS = "extract_requirements"
    ANALYZE_WORK_ITEM = "analyze_work_item"
    PLAN_WORK_ITEM = "plan_work_item"
    BUILD_CONTEXT = "build_context"
    RUN_WORK_ITEM = "run_work_item"
    EXECUTE_WORK_ITEM = "execute_work_item"
    VERIFY_EXECUTION = "verify_execution"
    CREATE_PULL_REQUEST = "create_pull_request"
    RECONCILE_PROJECT = "reconcile_project"


class CommandEnvelope(BaseModel):
    """Transport envelope for one canonical command (Task 24.1)."""

    command_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    command_type: CommandType
    project_id: ProjectId | None = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requested_by: ActorId | None = None
    trigger_type: TriggerType = TriggerType.INTERNAL
    correlation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    payload: dict[str, object] = Field(default_factory=dict)


class AnalyzeProjectCommand(BaseModel):
    project_id: ProjectId


class SyncRepositoryCommand(BaseModel):
    repository_id: RepositoryId


class IngestRepositoryCommand(BaseModel):
    repository_id: RepositoryId
    revision: str | None = None


class IngestDocumentCommand(BaseModel):
    document_id: uuid.UUID
    project_id: ProjectId | None = None


class ExtractRequirementsCommand(BaseModel):
    project_id: ProjectId
    document_id: uuid.UUID | None = None


class AnalyzeWorkItemCommand(BaseModel):
    work_item_id: WorkItemId


class PlanWorkItemCommand(BaseModel):
    work_item_id: WorkItemId


class BuildContextCommand(BaseModel):
    work_item_id: WorkItemId
    repository_id: RepositoryId | None = None
    revision: str | None = None
    budget: int = 8000


class RunWorkItemCommand(BaseModel):
    work_item_id: WorkItemId


class ExecuteWorkItemCommand(BaseModel):
    work_item_id: WorkItemId
    execution_id: ExecutionId | None = None


class VerifyExecutionCommand(BaseModel):
    execution_id: ExecutionId
    work_item_id: WorkItemId


class CreatePullRequestCommand(BaseModel):
    execution_id: ExecutionId
    work_item_id: WorkItemId


class ReconcileProjectCommand(BaseModel):
    project_id: ProjectId


COMMAND_TYPE_TO_MODEL: dict[CommandType, type[BaseModel]] = {
    CommandType.ANALYZE_PROJECT: AnalyzeProjectCommand,
    CommandType.SYNC_REPOSITORY: SyncRepositoryCommand,
    CommandType.INGEST_REPOSITORY: IngestRepositoryCommand,
    CommandType.INGEST_DOCUMENT: IngestDocumentCommand,
    CommandType.EXTRACT_REQUIREMENTS: ExtractRequirementsCommand,
    CommandType.ANALYZE_WORK_ITEM: AnalyzeWorkItemCommand,
    CommandType.PLAN_WORK_ITEM: PlanWorkItemCommand,
    CommandType.BUILD_CONTEXT: BuildContextCommand,
    CommandType.RUN_WORK_ITEM: RunWorkItemCommand,
    CommandType.EXECUTE_WORK_ITEM: ExecuteWorkItemCommand,
    CommandType.VERIFY_EXECUTION: VerifyExecutionCommand,
    CommandType.CREATE_PULL_REQUEST: CreatePullRequestCommand,
    CommandType.RECONCILE_PROJECT: ReconcileProjectCommand,
}


def make_command(
    command_type: CommandType,
    model: BaseModel,
    *,
    trigger_type: TriggerType = TriggerType.INTERNAL,
    requested_by: ActorId | None = None,
    correlation_id: uuid.UUID | None = None,
) -> CommandEnvelope:
    """Build a command envelope from a typed command payload."""
    return CommandEnvelope(
        command_type=command_type,
        project_id=getattr(model, "project_id", None),
        requested_by=requested_by,
        trigger_type=trigger_type,
        correlation_id=correlation_id or uuid.uuid4(),
        payload=model.model_dump(mode="json"),
    )


def command_to_model(envelope: CommandEnvelope) -> BaseModel | None:
    """Reconstruct the typed command payload, if known."""
    model = COMMAND_TYPE_TO_MODEL.get(envelope.command_type)
    if model is None:
        return None
    return model.model_validate(envelope.payload)


__all__ = [
    "AnalyzeProjectCommand",
    "AnalyzeWorkItemCommand",
    "BuildContextCommand",
    "COMMAND_TYPE_TO_MODEL",
    "CommandEnvelope",
    "CommandType",
    "CreatePullRequestCommand",
    "ExecuteWorkItemCommand",
    "ExtractRequirementsCommand",
    "IngestDocumentCommand",
    "IngestRepositoryCommand",
    "PlanWorkItemCommand",
    "ReconcileProjectCommand",
    "RunWorkItemCommand",
    "SyncRepositoryCommand",
    "TriggerType",
    "VerifyExecutionCommand",
    "command_to_model",
    "make_command",
]
