from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, SerializeAsAny, model_validator

from agent_core.agent_platform.agents.base.contracts import AgentRequest, AgentResult
from agent_core.agent_platform.config.models import AgentConfig


class AgentExecutionRequest(BaseModel):
    workflow_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str
    request: SerializeAsAny[AgentRequest]
    config: SerializeAsAny[AgentConfig]
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))

    @model_validator(mode="after")
    def agent_types_must_match(self) -> "AgentExecutionRequest":
        if self.agent_type != self.request.agent_type:
            raise ValueError("agent_type must match request.agent_type")
        if self.agent_type != self.config.agent_type:
            raise ValueError("agent_type must match config.agent_type")
        return self


class PersistedAgentResult(BaseModel):
    result_id: UUID = Field(default_factory=uuid4)
    result: SerializeAsAny[AgentResult]


@runtime_checkable
class AgentResultStore(Protocol):
    async def persist(self, result: AgentResult) -> PersistedAgentResult: ...


class InMemoryAgentResultStore(AgentResultStore):
    def __init__(self) -> None:
        self.results: list[PersistedAgentResult] = []

    async def persist(self, result: AgentResult) -> PersistedAgentResult:
        persisted = PersistedAgentResult(result=result)
        self.results.append(persisted)
        return persisted
