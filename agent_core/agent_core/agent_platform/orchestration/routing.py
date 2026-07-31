from __future__ import annotations

from pydantic import BaseModel

from agent_core.agent_platform.agents.base.contracts import AgentNextAction
from agent_core.agent_platform.orchestration.transitions import AgentTransition


class AgentRouteDecision(BaseModel):
    next_action: AgentNextAction = AgentNextAction.NONE
    next_agent_type: str | None
    requires_approval: bool
    escalate: bool
    reason: str


def route_transition(
    transition: AgentTransition,
    *,
    current_agent_type: str | None = None,
) -> AgentRouteDecision:
    if transition.next_action == AgentNextAction.RUN_PLANNING:
        return AgentRouteDecision(
            next_action=transition.next_action,
            next_agent_type="planning",
            requires_approval=False,
            escalate=False,
            reason=transition.reason,
        )
    if transition.next_action == AgentNextAction.RUN_CODING:
        return AgentRouteDecision(
            next_action=transition.next_action,
            next_agent_type="coding",
            requires_approval=False,
            escalate=False,
            reason=transition.reason,
        )
    if transition.next_action == AgentNextAction.RUN_VERIFICATION:
        return AgentRouteDecision(
            next_action=transition.next_action,
            next_agent_type="verification",
            requires_approval=False,
            escalate=False,
            reason=transition.reason,
        )
    if transition.next_action == AgentNextAction.REQUEST_APPROVAL:
        return AgentRouteDecision(
            next_action=transition.next_action,
            next_agent_type=None,
            requires_approval=True,
            escalate=False,
            reason=transition.reason,
        )
    if transition.next_action in {AgentNextAction.ESCALATE, AgentNextAction.REQUEST_CLARIFICATION}:
        return AgentRouteDecision(
            next_action=transition.next_action,
            next_agent_type=None,
            requires_approval=False,
            escalate=True,
            reason=transition.reason,
        )
    if transition.next_action == AgentNextAction.RETRY:
        if current_agent_type is None:
            return AgentRouteDecision(
                next_action=transition.next_action,
                next_agent_type=None,
                requires_approval=False,
                escalate=True,
                reason=f"{transition.reason} Retry target is unavailable.",
            )
        return AgentRouteDecision(
            next_action=transition.next_action,
            next_agent_type=current_agent_type,
            requires_approval=False,
            escalate=False,
            reason=transition.reason,
        )
    return AgentRouteDecision(
        next_action=transition.next_action,
        next_agent_type=None,
        requires_approval=False,
        escalate=False,
        reason=transition.reason,
    )
