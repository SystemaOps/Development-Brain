from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.base.contracts import AgentNextAction
from agent_core.agent_platform.orchestration.contracts import AgentExecutionRequest
from agent_core.agent_platform.orchestration.orchestrator import AgentOrchestrationResult
from agent_core.agent_platform.orchestration.routing import AgentRouteDecision


class AgentFlowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    TRANSITION_PENDING = "transition_pending"
    ESCALATED = "escalated"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    CHANGES_REQUESTED = "changes_requested"
    CANCELLED = "cancelled"


class AgentFlowStep(BaseModel):
    sequence: int = Field(ge=1)
    execution: AgentExecutionRequest
    outcome: AgentOrchestrationResult


class AgentFlowResult(BaseModel):
    flow_id: UUID | None = None
    version: int = Field(default=0, ge=0)
    workflow_id: str
    status: AgentFlowStatus
    steps: list[AgentFlowStep]
    final_outcome: AgentOrchestrationResult
    pending_route: AgentRouteDecision
    reason: str


@runtime_checkable
class AgentStepOrchestrator(Protocol):
    async def run_once(self, execution: AgentExecutionRequest) -> AgentOrchestrationResult: ...


@runtime_checkable
class AgentTransitionRequestResolver(Protocol):
    async def resolve_next(
        self,
        *,
        previous_execution: AgentExecutionRequest,
        previous_outcome: AgentOrchestrationResult,
        route: AgentRouteDecision,
    ) -> AgentExecutionRequest | None: ...


class InMemoryTransitionRequestResolver:
    """FIFO transition input for tests and explicitly assembled local flows."""

    def __init__(self, requests: list[AgentExecutionRequest] | None = None) -> None:
        self.requests = list(requests or [])

    async def resolve_next(
        self,
        *,
        previous_execution: AgentExecutionRequest,
        previous_outcome: AgentOrchestrationResult,
        route: AgentRouteDecision,
    ) -> AgentExecutionRequest | None:
        del previous_execution, previous_outcome, route
        if not self.requests:
            return None
        return self.requests.pop(0)


class AgentFlowOrchestrator:
    """Runs bounded cross-agent flows while delegating typed request translation."""

    def __init__(
        self,
        *,
        step_orchestrator: AgentStepOrchestrator,
        transition_resolver: AgentTransitionRequestResolver | None = None,
    ) -> None:
        self.step_orchestrator = step_orchestrator
        self.transition_resolver = transition_resolver

    async def run(
        self,
        initial_execution: AgentExecutionRequest,
        *,
        max_steps: int = 10,
    ) -> AgentFlowResult:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")

        current_execution = initial_execution
        steps: list[AgentFlowStep] = []

        for sequence in range(1, max_steps + 1):
            outcome = await self.step_orchestrator.run_once(current_execution)
            steps.append(
                AgentFlowStep(
                    sequence=sequence,
                    execution=current_execution,
                    outcome=outcome,
                )
            )

            terminal = _terminal_status(outcome)
            if terminal is not None:
                status, reason = terminal
                return _flow_result(initial_execution, status, steps, outcome, reason)

            if sequence == max_steps:
                return _flow_result(
                    initial_execution,
                    AgentFlowStatus.MAX_STEPS_EXCEEDED,
                    steps,
                    outcome,
                    f"Flow reached the configured {max_steps}-step limit before completion.",
                )

            if self.transition_resolver is None:
                return _flow_result(
                    initial_execution,
                    AgentFlowStatus.TRANSITION_PENDING,
                    steps,
                    outcome,
                    f"A typed {outcome.route.next_agent_type} request is required to continue.",
                )

            try:
                next_execution = await self.transition_resolver.resolve_next(
                    previous_execution=current_execution,
                    previous_outcome=outcome,
                    route=outcome.route,
                )
            except Exception as exc:
                return _flow_result(
                    initial_execution,
                    AgentFlowStatus.ESCALATED,
                    steps,
                    outcome,
                    f"Transition request resolution failed: {type(exc).__name__}: {exc}",
                )

            if next_execution is None:
                return _flow_result(
                    initial_execution,
                    AgentFlowStatus.TRANSITION_PENDING,
                    steps,
                    outcome,
                    f"No typed {outcome.route.next_agent_type} request is available yet.",
                )

            validation_error = _validate_transition(
                previous=current_execution,
                next_execution=next_execution,
                route=outcome.route,
            )
            if validation_error is not None:
                return _flow_result(
                    initial_execution,
                    AgentFlowStatus.ESCALATED,
                    steps,
                    outcome,
                    validation_error,
                )
            current_execution = next_execution

        raise AssertionError("Agent flow loop exited unexpectedly")


def _terminal_status(
    outcome: AgentOrchestrationResult,
) -> tuple[AgentFlowStatus, str] | None:
    route = outcome.route
    next_action = route.next_action
    if next_action == AgentNextAction.NONE:
        next_action = outcome.result.next_action

    if route.requires_approval:
        return AgentFlowStatus.WAITING_FOR_APPROVAL, route.reason
    if next_action == AgentNextAction.REQUEST_CLARIFICATION:
        return AgentFlowStatus.WAITING_FOR_CLARIFICATION, route.reason
    if route.escalate:
        return AgentFlowStatus.ESCALATED, route.reason
    if route.next_agent_type is None:
        return AgentFlowStatus.COMPLETED, route.reason
    return None


def _validate_transition(
    *,
    previous: AgentExecutionRequest,
    next_execution: AgentExecutionRequest,
    route: AgentRouteDecision,
) -> str | None:
    expected_agent_type = route.next_agent_type
    if next_execution.agent_type != expected_agent_type:
        return (
            f"Transition expected agent '{expected_agent_type}' but resolver returned "
            f"'{next_execution.agent_type}'."
        )
    if next_execution.workflow_id != previous.workflow_id:
        return "Transition request must preserve workflow_id."
    if next_execution.request.project_id != previous.request.project_id:
        return "Transition request must preserve project_id."
    return None


def _flow_result(
    initial_execution: AgentExecutionRequest,
    status: AgentFlowStatus,
    steps: list[AgentFlowStep],
    final_outcome: AgentOrchestrationResult,
    reason: str,
) -> AgentFlowResult:
    return AgentFlowResult(
        workflow_id=initial_execution.workflow_id,
        status=status,
        steps=steps,
        final_outcome=final_outcome,
        pending_route=final_outcome.route,
        reason=reason,
    )
