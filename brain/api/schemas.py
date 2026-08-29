"""API request/response schemas (Phase 23).

API schemas are explicit DTOs; routes never expose persistence models or raw
provider SDK types directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# --- system ---------------------------------------------------------------


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class AcceptedResult(BaseModel):
    command_id: str | None = None
    workflow_id: str | None = None
    status: str = "ACCEPTED"


# --- projects -------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    repositories: list[uuid.UUID] = Field(default_factory=list)
    external_refs: list[dict[str, object]] = Field(default_factory=list)


# --- repositories ---------------------------------------------------------


class RepositoryCreate(BaseModel):
    name: str
    clone_url: str
    default_branch: str = "main"


class RepositoryRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    clone_url: str
    default_branch: str
    current_revision: str | None = None
    external_refs: list[dict[str, object]] = Field(default_factory=list)


# --- documents ------------------------------------------------------------


class DocumentCreate(BaseModel):
    source_uri: str
    mime_type: str = "text/markdown"
    title: str | None = None


class DocumentRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str | None = None
    source_uri: str
    mime_type: str
    current_version_id: uuid.UUID | None = None


# --- requirements ---------------------------------------------------------


class RequirementCreate(BaseModel):
    project_id: uuid.UUID
    title: str
    description: str = ""
    key: str | None = None


class RequirementUpdate(BaseModel):
    title: str | None = None
    description: str | None = None


class RequirementRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    key: str | None = None
    title: str
    description: str = ""
    status: str


# --- work items -----------------------------------------------------------


class WorkItemCreate(BaseModel):
    project_id: uuid.UUID
    title: str
    description: str = ""
    type: str = "task"


class WorkItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None


class WorkItemRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str = ""
    type: str
    human_work_status: str
    implementation_status: str
    verification_status: str
    pull_request_status: str


# --- context --------------------------------------------------------------


class ContextBuildRequest(BaseModel):
    work_item_id: uuid.UUID
    project_id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None
    revision: str | None = None
    context_type: str = "coding"
    preferred_token_budget: int = 8000
    max_total_tokens: int = 32000


class ContextBuildResult(BaseModel):
    capsule_id: uuid.UUID
    work_item_id: uuid.UUID
    context_type: str
    total_tokens: int
    model_budget_tokens: int
    candidates_included: int
    candidates_gathered: int


# --- code -----------------------------------------------------------------


class CodeSearchRequest(BaseModel):
    query: str
    repository_id: uuid.UUID | None = None
    revision: str | None = None
    limit: int = 20


class ImpactAnalysisRequest(BaseModel):
    repository_id: uuid.UUID
    revision: str
    target_symbols: list[str] = Field(default_factory=list)
    task_concepts: list[str] = Field(default_factory=list)


# --- knowledge ------------------------------------------------------------


class KnowledgeSearchRequest(BaseModel):
    query: str
    project_id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None
    revision: str | None = None
    limit: int = 20


# --- executions -----------------------------------------------------------


class ExecutionCreate(BaseModel):
    work_item_id: uuid.UUID
    executor_id: uuid.UUID | None = None


class ExecutionRead(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    work_item_id: uuid.UUID
    executor_id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None = None


# --- verification ---------------------------------------------------------


class VerificationRequest(BaseModel):
    execution_id: uuid.UUID
    work_item_id: uuid.UUID
    acceptance_criteria: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    repository_id: uuid.UUID | None = None
    revision: str | None = None


class VerificationRead(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    verdict: str
    issues: list[str] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
    pr_allowed: bool = False


# --- pull requests --------------------------------------------------------


class PullRequestCreate(BaseModel):
    execution_id: uuid.UUID


class PullRequestRead(BaseModel):
    id: str
    external_ref: dict[str, object] = Field(default_factory=dict)
    status: str = "created"
