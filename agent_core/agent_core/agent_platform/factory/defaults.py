from __future__ import annotations

from agent_core.agent_platform.agents.coding import register_coding_agent
from agent_core.agent_platform.agents.planning import register_planning_agent
from agent_core.agent_platform.agents.verification import register_verification_agent
from agent_core.agent_platform.factory.agent_factory import AgentFactory
from agent_core.agent_platform.runtime.dependency_container import AgentDependencyContainer


def create_default_agent_factory(dependencies: AgentDependencyContainer | None = None) -> AgentFactory:
    factory = AgentFactory(dependencies=dependencies or AgentDependencyContainer())
    register_planning_agent(factory.registry)
    register_coding_agent(factory.registry)
    register_verification_agent(factory.registry)
    return factory
