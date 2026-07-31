from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.base.contracts import (
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from agent_core.domain.coding import CodingAttemptRequest, CodingAttemptResult


class CodingAgentRequest(AgentRequest):
    agent_type: Literal["coding"] = "coding"
    coding_attempt: CodingAttemptRequest | None = None
    approved: bool = False


class CodingAgentState(BaseModel):
    phase: str = "created"
    workflow_trace: list[str] = Field(default_factory=list)
    coding_attempt: CodingAttemptRequest | None = None
    result: CodingAttemptResult | None = None


class CodingAgentResult(AgentResult):
    agent_type: Literal["coding"] = "coding"
    status: AgentRunStatus
    coding_result: CodingAttemptResult | None = None
