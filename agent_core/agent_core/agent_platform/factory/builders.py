from __future__ import annotations

from typing import Protocol

from agent_core.agent_platform.agents.base.agent import BaseAgent
from agent_core.agent_platform.config.models import AgentConfig
from agent_core.agent_platform.runtime.dependency_container import AgentDependencyContainer


class AgentBuilder(Protocol):
    @property
    def agent_type(self) -> str:
        ...

    def build(self, *, config: AgentConfig, dependencies: AgentDependencyContainer) -> BaseAgent:
        ...
