from __future__ import annotations

from pydantic import Field

from agent_core.agent_platform.config.models import AgentConfig


class CodingAgentConfig(AgentConfig):
    agent_type: str = "coding"
    checkpoint_namespace: str = "coding"
    approval_required: bool = False
    workspace_strategy: str = "isolated"
    allowed_statuses: list[str] = Field(default_factory=lambda: ["approved", "ready"])
