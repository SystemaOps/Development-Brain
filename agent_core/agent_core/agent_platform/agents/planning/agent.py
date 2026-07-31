from __future__ import annotations

from pydantic import ValidationError

from agent_core.agent_platform.agents.base.agent import BaseAgent
from agent_core.agent_platform.agents.base.contracts import (
    AgentRequest,
)
from agent_core.agent_platform.agents.base.errors import AgentValidationError
from agent_core.agent_platform.agents.planning.config import PlanningAgentConfig
from agent_core.agent_platform.agents.planning.state import (
    PlanningAgentRequest,
    PlanningAgentResult,
)
from agent_core.agent_platform.agents.planning.workflow import (
    build_planning_agent_workflow,
)
from agent_core.agent_platform.config.models import AgentConfig, materialize_agent_config
from agent_core.agent_platform.factory.builders import AgentBuilder
from agent_core.agent_platform.factory.registry import AgentBuilderRegistry
from agent_core.agent_platform.runtime.dependency_container import AgentDependencyContainer
from agent_core.agent_platform.runtime.execution_context import AgentExecutionContext


class PlanningAgent(BaseAgent):
    def __init__(
        self, *, config: PlanningAgentConfig, dependencies: AgentDependencyContainer
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.workflow = build_planning_agent_workflow(config, dependencies)
        self.workflow_steps = self.workflow.steps
        self._initialized = False

    @property
    def agent_type(self) -> str:
        return "planning"

    async def initialize(self) -> None:
        self._initialized = True

    async def validate_request(self, request: AgentRequest) -> None:
        try:
            typed = PlanningAgentRequest.model_validate(request.model_dump(mode="json"))
        except ValidationError as exc:
            raise AgentValidationError(
                "PlanningAgent received an invalid planning request"
            ) from exc
        if typed.agent_type != self.agent_type:
            raise AgentValidationError("PlanningAgent only accepts planning requests")
        if not (typed.objective or typed.original_request or typed.plan or typed.session_id):
            raise AgentValidationError(
                "Planning requests require an objective, original request, plan, or session_id"
            )

    async def execute(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> PlanningAgentResult:
        typed = PlanningAgentRequest.model_validate(request.model_dump(mode="json"))
        return await self.workflow.run(typed, context)

    async def shutdown(self) -> None:
        self._initialized = False


class PlanningAgentBuilder(AgentBuilder):
    @property
    def agent_type(self) -> str:
        return "planning"

    def build(self, *, config: AgentConfig, dependencies: AgentDependencyContainer) -> BaseAgent:
        return PlanningAgent(
            config=PlanningAgentConfig.model_validate(materialize_agent_config(config)),
            dependencies=dependencies,
        )


def register_planning_agent(registry: AgentBuilderRegistry) -> None:
    registry.register("planning", PlanningAgentBuilder())
