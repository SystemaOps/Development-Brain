from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from agent_core.enums import InputMode, PlanNodeKind, RepositoryAccessMode


class ProjectCreate(BaseModel):
    project_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,78}$")
    name: str = Field(min_length=3, max_length=200)
    description: str | None = None
    source_type: str | None = "manual_request"


class ProjectView(BaseModel):
    id: UUID
    project_key: str
    name: str
    description: str | None
    status: str


class DocumentView(BaseModel):
    id: UUID
    project_key: str
    filename: str
    document_type: str
    status: str
    chunk_count: int


class DocumentChunkView(BaseModel):
    id: UUID
    chunk_index: int
    heading_path: list[str]
    title: str | None
    token_estimate: int


class PlanningSessionCreate(BaseModel):
    project_key: str
    input_mode: InputMode = InputMode.TEXT
    original_request: str = Field(min_length=10)
    intake: dict[str, Any] = Field(default_factory=dict)


class ClarificationQuestionView(BaseModel):
    id: UUID
    question_key: str
    question: str
    reason: str
    blocking: bool
    answer_format: str | None
    answer: str | None
    status: str


class PlanningSessionView(BaseModel):
    id: UUID
    project_key: str
    status: str
    input_mode: str
    original_request: str | None
    questions: list[ClarificationQuestionView] = Field(default_factory=list)


class AnswerQuestionsRequest(BaseModel):
    answers: dict[str, str] = Field(min_length=1)


class AcceptanceCriterionSpec(BaseModel):
    key: str
    statement: str
    verification_method: str


class PlanNodeSpec(BaseModel):
    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{2,118}$")
    kind: PlanNodeKind
    title: str
    objective: str
    rationale: str | None = None
    parent_stable_key: str | None = None
    inherited_context: list[str] = Field(default_factory=list)
    local_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    likely_components: list[str] = Field(default_factory=list)
    priority: str | None = "normal"
    size_estimate: str | None = "unknown"
    acceptance_criteria: list[AcceptanceCriterionSpec] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ProjectPlanSpec(BaseModel):
    summary: str
    rationale: str | None = None
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    components: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[PlanNodeSpec]

    @model_validator(mode="after")
    def validate_hierarchy(self) -> "ProjectPlanSpec":
        keys = {n.stable_key for n in self.nodes}
        visions = [n for n in self.nodes if n.kind == PlanNodeKind.VISION]
        if len(visions) != 1:
            raise ValueError("Plan must contain exactly one Vision")
        by_key = {n.stable_key: n for n in self.nodes}
        allowed = {
            PlanNodeKind.CAPABILITY: PlanNodeKind.VISION,
            PlanNodeKind.EPIC: PlanNodeKind.CAPABILITY,
            PlanNodeKind.STORY: PlanNodeKind.EPIC,
            PlanNodeKind.TASK: PlanNodeKind.STORY,
        }
        for node in self.nodes:
            if node.kind == PlanNodeKind.VISION:
                if node.parent_stable_key:
                    raise ValueError("Vision cannot have parent")
            else:
                if not node.parent_stable_key or node.parent_stable_key not in keys:
                    raise ValueError(f"Missing parent for {node.stable_key}")
                if by_key[node.parent_stable_key].kind != allowed[node.kind]:
                    raise ValueError(f"Invalid parent level for {node.stable_key}")
            if node.kind == PlanNodeKind.TASK and not node.acceptance_criteria:
                raise ValueError(f"Task {node.stable_key} needs acceptance criteria")
            for dep in node.dependencies:
                if dep not in keys:
                    raise ValueError(f"Unknown dependency {dep}")
        return self


class PlanVersionView(BaseModel):
    id: UUID
    project_key: str
    version_number: int
    status: str
    summary: str | None


class ProvisionProjectResponse(BaseModel):
    project_key: str
    jobs_created: int
    job_ids: list[UUID]


class ContextCapsuleView(BaseModel):
    id: UUID
    plan_node_id: UUID
    capsule_type: str
    content: str
    token_estimate: int | None


class RepositoryBindingCreate(BaseModel):
    repository_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    mount_path: str = Field(min_length=1)
    access_mode: RepositoryAccessMode = RepositoryAccessMode.READ_ONLY
    write_allowlist: list[str] = Field(default_factory=list)
    denylist: list[str] | None = None
    command_allowlist: list[str] = Field(default_factory=list)


class RepositoryBindingView(BaseModel):
    repository_key: str
    mount_path: str
    access_mode: RepositoryAccessMode
    write_allowlist: list[str]
    denylist: list[str]
    command_allowlist: list[str]


class RepositoryIndexView(BaseModel):
    project_id: UUID
    project_key: str
    repository_key: str
    symbol_count: int
    relationship_count: int
    warnings: list[str] = Field(default_factory=list)
    graph_mutations: int = 0
    vector_upserts: int = 0


class RepositorySnapshotView(BaseModel):
    repository_key: str
    commit_sha: str | None
    branch: str | None
    dirty: bool
    status_porcelain: str
    warning: str | None = None


class CodeSymbolView(BaseModel):
    symbol_key: str
    repository_key: str
    relative_path: str
    name: str
    kind: str
    language: str
    start_line: int | None = None
    end_line: int | None = None
    parent_symbol_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeRelationshipView(BaseModel):
    repository_key: str
    source_symbol_key: str
    relationship_type: str
    target_symbol_key: str | None = None
    target_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
