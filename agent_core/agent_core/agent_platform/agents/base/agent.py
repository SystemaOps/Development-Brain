from __future__ import annotations

from abc import ABC, abstractmethod

from agent_core.agent_platform.agents.base.contracts import AgentRequest, AgentResult
from agent_core.agent_platform.runtime.execution_context import AgentExecutionContext


class BaseAgent(ABC):
    @property
    @abstractmethod
    def agent_type(self) -> str:
        ...

    @abstractmethod
    async def initialize(self) -> None:
        ...

    @abstractmethod
    async def validate_request(self, request: AgentRequest) -> None:
        ...

    @abstractmethod
    async def execute(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> AgentResult:
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        ...
