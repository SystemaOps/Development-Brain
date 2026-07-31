from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from agent_core.agent_platform.adapters import (
    CommandRunner,
    GitRepository,
    GraphRepository,
    LLMClient,
    ProjectRepository,
    RepositoryAnalysisGateway,
    SemanticContextStore,
    WorkPackageGateway,
)
from agent_core.agent_platform.runtime.checkpointing import CheckpointStore, InMemoryCheckpointStore
from agent_core.agent_platform.runtime.event_bus import AgentEventBus, InMemoryAgentEventBus
from agent_core.domain.coding import CodingAttemptRequest, CodingAttemptResult


class PlanningDraft(Protocol):
    plan_json: Any


@runtime_checkable
class PlanningServiceDependency(Protocol):
    async def draft_plan(self, session_id: UUID) -> PlanningDraft:
        ...


@runtime_checkable
class CodingServiceDependency(Protocol):
    async def run_explicit_attempt(
        self,
        *,
        project_key: str,
        request: CodingAttemptRequest,
    ) -> CodingAttemptResult:
        ...


class AgentDependencyContainer(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: object | None = None
    llm_client: SkipValidation[LLMClient | None] = None
    skill_registry: object | None = None
    planning_service: SkipValidation[PlanningServiceDependency | None] = None
    coding_service: SkipValidation[CodingServiceDependency | None] = None
    repository_service: SkipValidation[RepositoryAnalysisGateway | None] = None
    project_repository: SkipValidation[ProjectRepository | None] = None
    graph_repository: SkipValidation[GraphRepository | None] = None
    context_store: SkipValidation[SemanticContextStore | None] = None
    work_package_gateway: SkipValidation[WorkPackageGateway | None] = None
    repository: SkipValidation[GitRepository | None] = None
    command_runner: SkipValidation[CommandRunner | None] = None
    checkpoint_store: SkipValidation[CheckpointStore] = Field(default_factory=InMemoryCheckpointStore)
    event_bus: SkipValidation[AgentEventBus] = Field(default_factory=InMemoryAgentEventBus)
    result_store: object | None = None

    def with_overrides(self, **overrides: Any) -> "AgentDependencyContainer":
        return self.model_copy(update=overrides)
