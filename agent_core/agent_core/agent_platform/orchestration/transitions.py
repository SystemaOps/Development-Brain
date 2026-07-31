from __future__ import annotations

from pydantic import BaseModel

from agent_core.agent_platform.agents.base.contracts import AgentNextAction, AgentResult, AgentRunStatus
from agent_core.agent_platform.agents.verification.state import VerificationAgentResult, VerificationVerdict
from agent_core.agent_platform.config.models import AgentConfig


class AgentTransition(BaseModel):
    next_action: AgentNextAction
    reason: str


def decide_next_transition(result: AgentResult, config: AgentConfig) -> AgentTransition:
    if result.next_action != AgentNextAction.NONE:
        return AgentTransition(next_action=result.next_action, reason="Agent requested explicit next action.")

    if result.status == AgentRunStatus.BLOCKED:
        return AgentTransition(next_action=AgentNextAction.ESCALATE, reason="Agent result is blocked.")
    if result.status == AgentRunStatus.FAILED:
        return AgentTransition(next_action=AgentNextAction.RETRY, reason="Agent result failed.")
    if result.agent_type == "planning":
        if config.approval_required:
            return AgentTransition(next_action=AgentNextAction.REQUEST_APPROVAL, reason="Planning approval is required by configuration.")
        return AgentTransition(next_action=AgentNextAction.RUN_CODING, reason="Planning completed without approval gate.")
    if result.agent_type == "coding":
        return AgentTransition(next_action=AgentNextAction.RUN_VERIFICATION, reason="Coding completed.")
    if isinstance(result, VerificationAgentResult):
        return _verification_transition(result)
    if result.agent_type == "verification":
        verdict = result.metadata.get("verdict")
        if verdict == VerificationVerdict.CHANGES_REQUESTED.value:
            return AgentTransition(next_action=AgentNextAction.RUN_CODING, reason="Verification requested changes.")
        if verdict == VerificationVerdict.BLOCKED.value:
            return AgentTransition(next_action=AgentNextAction.ESCALATE, reason="Verification is blocked.")
    return AgentTransition(next_action=AgentNextAction.COMPLETE, reason="Agent flow completed.")


def _verification_transition(result: VerificationAgentResult) -> AgentTransition:
    if result.verdict == VerificationVerdict.CHANGES_REQUESTED:
        return AgentTransition(next_action=AgentNextAction.RUN_CODING, reason="Verification requested changes.")
    if result.verdict == VerificationVerdict.BLOCKED:
        return AgentTransition(next_action=AgentNextAction.ESCALATE, reason="Verification is blocked.")
    return AgentTransition(next_action=AgentNextAction.COMPLETE, reason="Verification passed.")
