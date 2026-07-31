from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

from agent_core.agent_platform.agents.base.contracts import StateReference
from agent_core.agent_platform.config.models import AgentConfig
from agent_core.agent_platform.runtime.dependency_container import (
    AgentDependencyContainer,
)
from agent_core.agent_platform.runtime.execution_context import (
    AgentExecutionContext,
)

AgentConfigT = TypeVar("AgentConfigT", bound=AgentConfig)


@dataclass(frozen=True)
class AgentWorkflowRuntime(Generic[AgentConfigT]):
    config: AgentConfigT
    dependencies: AgentDependencyContainer
    execution_context: AgentExecutionContext


async def persist_workflow_state(
    runtime: AgentWorkflowRuntime,
    state: BaseModel,
) -> StateReference:
    checkpoint = runtime.execution_context.checkpoint
    checkpoint_id = await runtime.dependencies.checkpoint_store.save(
        identity=checkpoint,
        state=state.model_dump(mode="json"),
    )
    return StateReference(
        namespace=checkpoint.agent_type,
        key=checkpoint.key,
        checkpoint_id=checkpoint_id,
    )
