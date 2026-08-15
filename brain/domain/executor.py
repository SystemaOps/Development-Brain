"""Executor abstraction domain model (Phase 12).

Describes executors (Pi, fake, custom agents) through capability profiles and
registry descriptors.  The core never depends on a coding agent's session
model: only these canonical descriptors plus the ``ExecutionRequest`` /
``ExecutionResult`` crossing the port.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class ExecutorKind(StrEnum):
    PI = "pi"
    FAKE = "fake"
    CUSTOM = "custom"


class ModelDeployment(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class CostClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutorCapabilities(BaseModel):
    """What an executor can actually do (Task 12.1)."""

    coding: bool = True
    reasoning: bool = True
    tool_support: bool = True
    local_models: bool = False
    remote_models: bool = True
    context_window: int = 128000
    preferred_context_budget: int = 8000
    cost_class: CostClass = CostClass.MEDIUM
    deployment: ModelDeployment = ModelDeployment.REMOTE
    supported_tools: list[str] = Field(default_factory=list)


class ModelCapabilityProfile(BaseModel):
    """Representation of a model's capabilities (Task 12.2)."""

    name: str
    context_window: int = 128000
    preferred_context_budget: int = 8000
    coding: bool = True
    reasoning: bool = True
    tool_support: bool = True
    deployment: ModelDeployment = ModelDeployment.REMOTE
    cost_class: CostClass = CostClass.MEDIUM

    def to_capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(
            coding=self.coding,
            reasoning=self.reasoning,
            tool_support=self.tool_support,
            context_window=self.context_window,
            preferred_context_budget=self.preferred_context_budget,
            cost_class=self.cost_class,
            deployment=self.deployment,
        )


class ExecutorDescriptor(BaseModel):
    """Registry entry describing an available executor (Task 12.1)."""

    executor_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    kind: ExecutorKind = ExecutorKind.CUSTOM
    capabilities: ExecutorCapabilities = Field(default_factory=ExecutorCapabilities)
    supports_structured_tools: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class ExecutorSelection(BaseModel):
    """The chosen executor for an execution request."""

    descriptor: ExecutorDescriptor
    reason: str = ""


__all__ = [
    "CostClass",
    "ExecutorCapabilities",
    "ExecutorDescriptor",
    "ExecutorKind",
    "ExecutorSelection",
    "ModelCapabilityProfile",
    "ModelDeployment",
]
