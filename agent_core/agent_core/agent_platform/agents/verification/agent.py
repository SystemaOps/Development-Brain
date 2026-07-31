from __future__ import annotations

from pydantic import ValidationError

from agent_core.agent_platform.agents.base.agent import BaseAgent
from agent_core.agent_platform.agents.base.contracts import AgentRequest
from agent_core.agent_platform.agents.base.errors import AgentValidationError
from agent_core.agent_platform.agents.verification.config import VerificationAgentConfig
from agent_core.agent_platform.agents.verification.state import (
    VerificationAgentRequest,
    VerificationAgentResult,
)
from agent_core.agent_platform.agents.verification.workflow import (
    build_verification_agent_workflow,
)
from agent_core.agent_platform.config.models import AgentConfig, materialize_agent_config
from agent_core.agent_platform.factory.builders import AgentBuilder
from agent_core.agent_platform.factory.registry import AgentBuilderRegistry
from agent_core.agent_platform.runtime.dependency_container import AgentDependencyContainer
from agent_core.agent_platform.runtime.execution_context import AgentExecutionContext


class VerificationAgent(BaseAgent):
    def __init__(
        self, *, config: VerificationAgentConfig, dependencies: AgentDependencyContainer
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.workflow = build_verification_agent_workflow(config, dependencies)
        self.workflow_steps = self.workflow.steps
        self._initialized = False

    @property
    def agent_type(self) -> str:
        return "verification"

    async def initialize(self) -> None:
        self._initialized = True

    async def validate_request(self, request: AgentRequest) -> None:
        try:
            typed = VerificationAgentRequest.model_validate(request.model_dump(mode="json"))
        except ValidationError as exc:
            raise AgentValidationError(
                "VerificationAgent received an invalid verification request"
            ) from exc
        if typed.agent_type != self.agent_type:
            raise AgentValidationError("VerificationAgent only accepts verification requests")
        if not typed.task_id:
            raise AgentValidationError("Verification requests require task_id")
        if typed.coding_result is None and not typed.repository_diff:
            raise AgentValidationError("Verification requires a coding result or repository diff")

    async def execute(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> VerificationAgentResult:
        typed = VerificationAgentRequest.model_validate(request.model_dump(mode="json"))
        return await self.workflow.run(typed, context)

    async def shutdown(self) -> None:
        self._initialized = False


class VerificationAgentBuilder(AgentBuilder):
    @property
    def agent_type(self) -> str:
        return "verification"

    def build(self, *, config: AgentConfig, dependencies: AgentDependencyContainer) -> BaseAgent:
        return VerificationAgent(
            config=VerificationAgentConfig.model_validate(materialize_agent_config(config)),
            dependencies=dependencies,
        )


def register_verification_agent(registry: AgentBuilderRegistry) -> None:
    registry.register("verification", VerificationAgentBuilder())
