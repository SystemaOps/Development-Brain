from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field


class AgentLifecycleEventType(StrEnum):
    CREATED = "agent.created"
    STARTED = "agent.started"
    STEP_STARTED = "agent.step.started"
    STEP_COMPLETED = "agent.step.completed"
    INTERRUPTED = "agent.interrupted"
    FAILED = "agent.failed"
    COMPLETED = "agent.completed"
    RESULT_PERSISTED = "agent.result.persisted"
    TRANSITION_REQUESTED = "agent.transition.requested"


class AgentLifecycleEvent(BaseModel):
    event_type: AgentLifecycleEventType
    execution_id: UUID
    project_id: str
    task_id: str | None = None
    agent_type: str
    agent_instance_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str
    step_name: str | None = None
    correlation_id: str
    metadata: dict = Field(default_factory=dict)


@runtime_checkable
class AgentEventBus(Protocol):
    async def emit(self, event: AgentLifecycleEvent) -> None:
        ...


class InMemoryAgentEventBus(AgentEventBus):
    def __init__(self) -> None:
        self.events: list[AgentLifecycleEvent] = []

    async def emit(self, event: AgentLifecycleEvent) -> None:
        self.events.append(event)


class StructuredLoggingAgentEventBus(AgentEventBus):
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("agent_core.agent_platform")

    async def emit(self, event: AgentLifecycleEvent) -> None:
        self.logger.info(json.dumps(event.model_dump(mode="json"), sort_keys=True))
