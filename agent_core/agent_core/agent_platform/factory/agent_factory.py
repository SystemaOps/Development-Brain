from __future__ import annotations

from agent_core.agent_platform.agents.base.agent import BaseAgent
from agent_core.agent_platform.config.models import AgentConfig
from agent_core.agent_platform.factory.builders import AgentBuilder
from agent_core.agent_platform.factory.registry import AgentBuilderRegistry
from agent_core.agent_platform.runtime.dependency_container import AgentDependencyContainer


class AgentFactory:
    def __init__(self, *, dependencies: AgentDependencyContainer | None = None) -> None:
        self.dependencies = dependencies or AgentDependencyContainer()
        self.registry = AgentBuilderRegistry()

    def register(self, agent_type: str, builder: AgentBuilder) -> None:
        self.registry.register(agent_type, builder)

    def create(self, *, agent_type: str, config: AgentConfig) -> BaseAgent:
        if not config.enabled:
            raise ValueError(f"Agent type is disabled: {agent_type}")
        if config.agent_type != agent_type:
            raise ValueError(
                f"Requested agent_type '{agent_type}' does not match config agent_type '{config.agent_type}'"
            )
        builder = self.registry.get(agent_type)
        return builder.build(config=config, dependencies=self.dependencies)
