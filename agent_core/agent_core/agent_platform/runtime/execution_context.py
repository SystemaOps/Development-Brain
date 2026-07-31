from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class CheckpointIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str
    workflow_id: str
    agent_type: str
    agent_instance_id: str
    execution_id: UUID
    thread_id: str
    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))

    @property
    def namespace(self) -> tuple[str, str, str, str]:
        return (
            self.project_id,
            self.workflow_id,
            self.agent_type,
            self.agent_instance_id,
        )

    @property
    def key(self) -> str:
        return f"{self.thread_id}:{self.execution_id}:{self.checkpoint_id}"


class AgentExecutionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_id: UUID
    project_id: str
    task_id: str | None = None
    workflow_id: str
    agent_type: str
    agent_instance_id: str
    thread_id: str
    checkpoint: CheckpointIdentity
    correlation_id: str
    approval_required: bool = False
    metadata: dict = Field(default_factory=dict)
