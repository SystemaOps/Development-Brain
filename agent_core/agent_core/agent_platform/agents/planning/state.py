from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.base.contracts import (
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from agent_core.schemas import ProjectPlanSpec
from agent_core.skills.plan_validation import PlanValidationOutput
from agent_core.skills.requirement_extraction import NormalizedRequirement


class PlanningDocumentChunk(BaseModel):
    chunk_id: str
    title: str | None = None
    content: str
    document_id: str | None = None
    chunk_index: int | None = None
    heading_path: list[str] = Field(default_factory=list)


class PlanningAgentRequest(AgentRequest):
    agent_type: Literal["planning"] = "planning"
    original_request: str | None = None
    document_chunks: list[PlanningDocumentChunk] = Field(default_factory=list)
    plan: ProjectPlanSpec | None = None
    session_id: UUID | None = None
    clarification_required: bool = False


class PlanningAgentState(BaseModel):
    phase: str = "created"
    workflow_trace: list[str] = Field(default_factory=list)
    extracted_requirements: list[NormalizedRequirement] = Field(default_factory=list)
    plan: ProjectPlanSpec | None = None
    validation: PlanValidationOutput | None = None
    warnings: list[str] = Field(default_factory=list)


class PlanningAgentResult(AgentResult):
    agent_type: Literal["planning"] = "planning"
    status: AgentRunStatus
    requirements: list[NormalizedRequirement] = Field(default_factory=list)
    plan: ProjectPlanSpec | None = None
    validation: PlanValidationOutput | None = None
    clarification_questions: list[str] = Field(default_factory=list)
    projection_specs: dict[str, Any] = Field(default_factory=dict)
