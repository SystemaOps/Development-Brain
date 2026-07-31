from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LLMEndpointConfig(BaseModel):
    base_url: str = "http://localhost:8080/v1"
    model: str = "local-coding-model"
    timeout_seconds: int = Field(default=180, ge=1)
    context_window: int = Field(default=29696, ge=1024)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_type: str
    enabled: bool = True
    implementation: str = "default"
    checkpoint_namespace: str
    approval_required: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def checkpoint_namespace_must_be_present(self) -> "AgentConfig":
        if not self.checkpoint_namespace.strip():
            raise ValueError("checkpoint_namespace cannot be blank")
        return self


class AgentFlowRuntimeConfig(BaseModel):
    lease_seconds: int = Field(default=300, ge=1, le=86400)
    heartbeat_seconds: float = Field(default=60.0, gt=0)
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    recovery_enabled: bool = True
    max_recovery_attempts: int = Field(default=3, ge=0, le=100)

    @model_validator(mode="after")
    def heartbeat_must_precede_lease_expiry(self) -> "AgentFlowRuntimeConfig":
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("heartbeat_seconds must be less than lease_seconds")
        return self


class AgentPlatformConfig(BaseModel):
    agents: dict[str, AgentConfig]
    llm: LLMEndpointConfig = Field(default_factory=LLMEndpointConfig)
    flow_runtime: AgentFlowRuntimeConfig = Field(default_factory=AgentFlowRuntimeConfig)

    @model_validator(mode="after")
    def agent_keys_must_match_agent_types(self) -> "AgentPlatformConfig":
        for key, config in self.agents.items():
            if key != config.agent_type:
                raise ValueError(
                    f"agent config key '{key}' does not match agent_type '{config.agent_type}'"
                )
        return self


DEFAULT_AGENT_PLATFORM_CONFIG = AgentPlatformConfig(
    agents={
        "planning": AgentConfig(
            agent_type="planning",
            enabled=True,
            implementation="default",
            checkpoint_namespace="planning",
            approval_required=True,
        ),
        "coding": AgentConfig(
            agent_type="coding",
            enabled=True,
            implementation="default",
            checkpoint_namespace="coding",
            approval_required=False,
            settings={"workspace_strategy": "isolated"},
        ),
        "verification": AgentConfig(
            agent_type="verification",
            enabled=True,
            implementation="default",
            checkpoint_namespace="verification",
            approval_required=False,
            settings={
                "independent_workspace": True,
                "require_diff_for_pass": True,
                "require_test_command_for_pass": False,
                "require_test_evidence_for_source_changes": False,
                "security_review_enabled": True,
                "openproject_projection_enabled": True,
                "openproject_verified_status_name": "Verified",
                "openproject_changes_required_status_name": "Changes required",
                "openproject_blocked_status_name": "Blocked",
                "openproject_override_status_name": "Done",
                "human_override_enabled": False,
            },
        ),
    }
)


def materialize_agent_config(config: AgentConfig) -> dict[str, Any]:
    payload = config.model_dump()
    for key, value in config.settings.items():
        payload.setdefault(key, value)
    return payload
