from __future__ import annotations

from pydantic import ValidationError

from agent_core.agent_platform.agents.base.agent import BaseAgent
from agent_core.agent_platform.agents.base.contracts import AgentRequest
from agent_core.agent_platform.agents.base.errors import AgentValidationError
from agent_core.agent_platform.agents.coding.config import CodingAgentConfig
from agent_core.agent_platform.agents.coding.state import (
    CodingAgentRequest,
    CodingAgentResult,
)
from agent_core.agent_platform.agents.coding.workflow import build_coding_agent_workflow
from agent_core.agent_platform.config.models import AgentConfig, materialize_agent_config
from agent_core.agent_platform.factory.builders import AgentBuilder
from agent_core.agent_platform.factory.registry import AgentBuilderRegistry
from agent_core.agent_platform.runtime.dependency_container import AgentDependencyContainer
from agent_core.agent_platform.runtime.execution_context import AgentExecutionContext


class CodingAgent(BaseAgent):
    def __init__(
        self, *, config: CodingAgentConfig, dependencies: AgentDependencyContainer
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.workflow = build_coding_agent_workflow(config, dependencies)
        self.workflow_steps = self.workflow.steps
        self._initialized = False

    @property
    def agent_type(self) -> str:
        return "coding"

    async def initialize(self) -> None:
        self._initialized = True

    async def validate_request(self, request: AgentRequest) -> None:
        try:
            typed = CodingAgentRequest.model_validate(request.model_dump(mode="json"))
        except ValidationError as exc:
            raise AgentValidationError("CodingAgent received an invalid coding request") from exc
        if typed.agent_type != self.agent_type:
            raise AgentValidationError("CodingAgent only accepts coding requests")
        if not typed.task_id:
            raise AgentValidationError("Coding requests require task_id")
        if typed.coding_attempt is None:
            raise AgentValidationError("Coding requests require a coding_attempt payload")
        if not typed.approved:
            raise AgentValidationError("Coding requests must be approved before execution")

    async def execute(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> CodingAgentResult:
        typed = CodingAgentRequest.model_validate(request.model_dump(mode="json"))
        return await self.workflow.run(typed, context)

    async def shutdown(self) -> None:
        self._initialized = False


class CodingAgentBuilder(AgentBuilder):
    @property
    def agent_type(self) -> str:
        return "coding"

    def build(self, *, config: AgentConfig, dependencies: AgentDependencyContainer) -> BaseAgent:
        return CodingAgent(
            config=CodingAgentConfig.model_validate(materialize_agent_config(config)),
            dependencies=dependencies,
        )


def register_coding_agent(registry: AgentBuilderRegistry) -> None:
    registry.register("coding", CodingAgentBuilder())
