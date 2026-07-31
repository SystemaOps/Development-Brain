from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent_core.agent_platform.agents.base import AgentRequest
from agent_core.agent_platform.agents.coding import CodingAgentRequest
from agent_core.agent_platform.agents.planning import PlanningAgentRequest
from agent_core.agent_platform.agents.verification import (
    VerificationAgentRequest,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.orchestration import AgentExecutionRequest


class AgentExecutionCodecError(ValueError):
    pass


class AgentExecutionRequestCodec:
    def __init__(self) -> None:
        self._request_types: dict[str, type[AgentRequest]] = {}

    def register(
        self,
        agent_type: str,
        request_type: type[AgentRequest],
    ) -> None:
        if not agent_type.strip():
            raise AgentExecutionCodecError("Execution request agent type cannot be blank")
        if agent_type in self._request_types:
            raise AgentExecutionCodecError(
                f"Execution request codec already registered: {agent_type}"
            )
        self._request_types[agent_type] = request_type

    def decode(self, payload: dict[str, Any]) -> AgentExecutionRequest:
        agent_type = payload.get("agent_type")
        request_type = self._request_types.get(str(agent_type))
        if request_type is None:
            raise AgentExecutionCodecError(f"Unknown execution request agent type: {agent_type}")
        request_payload = payload.get("request")
        config_payload = payload.get("config")
        if not isinstance(request_payload, dict):
            raise AgentExecutionCodecError("Execution request payload is missing request")
        if not isinstance(config_payload, dict):
            raise AgentExecutionCodecError("Execution request payload is missing config")
        workflow_id = payload.get("workflow_id")
        correlation_id = payload.get("correlation_id")
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise AgentExecutionCodecError("Execution request payload is missing workflow_id")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise AgentExecutionCodecError("Execution request payload is missing correlation_id")
        try:
            return AgentExecutionRequest(
                workflow_id=workflow_id,
                agent_type=str(agent_type),
                request=request_type.model_validate(request_payload),
                config=AgentConfig.model_validate(config_payload),
                correlation_id=correlation_id,
            )
        except ValidationError as exc:
            raise AgentExecutionCodecError(
                f"Invalid {agent_type} execution request payload"
            ) from exc


def create_default_agent_execution_codec() -> AgentExecutionRequestCodec:
    codec = AgentExecutionRequestCodec()
    codec.register("planning", PlanningAgentRequest)
    codec.register("coding", CodingAgentRequest)
    codec.register("verification", VerificationAgentRequest)
    return codec
