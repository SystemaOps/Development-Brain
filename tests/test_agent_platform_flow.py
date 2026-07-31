from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowOrchestrator,
    AgentFlowStatus,
    AgentOrchestrationResult,
    AgentRouteDecision,
    AgentTransition,
    InMemoryTransitionRequestResolver,
    PersistedAgentResult,
    route_transition,
)
from agent_core.agent_platform.runtime import AgentDependencyContainer
from agent_core.services.agent_platform_service import AgentPlatformService


class ScriptedStepOrchestrator:
    def __init__(self, outcomes: list[AgentOrchestrationResult]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[AgentExecutionRequest] = []

    async def run_once(
        self,
        execution: AgentExecutionRequest,
    ) -> AgentOrchestrationResult:
        self.calls.append(execution)
        if not self.outcomes:
            raise AssertionError("No scripted outcome remains")
        return self.outcomes.pop(0)


def _execution(
    agent_type: str,
    *,
    workflow_id: str = "workflow-1",
    project_id: str = "demo",
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        workflow_id=workflow_id,
        agent_type=agent_type,
        request=AgentRequest(
            project_id=project_id,
            task_id="task-1",
            agent_type=agent_type,
            objective=f"Run {agent_type}",
        ),
        config=AgentConfig(
            agent_type=agent_type,
            checkpoint_namespace=agent_type,
        ),
        correlation_id="correlation-1",
    )


def _outcome(
    agent_type: str,
    *,
    next_action: AgentNextAction,
    next_agent_type: str | None,
    requires_approval: bool = False,
    escalate: bool = False,
    status: AgentRunStatus = AgentRunStatus.SUCCEEDED,
) -> AgentOrchestrationResult:
    result = AgentResult(
        execution_id=uuid4(),
        project_id="demo",
        task_id="task-1",
        agent_type=agent_type,
        status=status,
        summary=f"{agent_type} outcome",
        next_action=next_action,
    )
    return AgentOrchestrationResult(
        result=result,
        persisted=PersistedAgentResult(result=result),
        route=AgentRouteDecision(
            next_action=next_action,
            next_agent_type=next_agent_type,
            requires_approval=requires_approval,
            escalate=escalate,
            reason=f"Route after {agent_type}",
        ),
    )


def test_execution_request_requires_matching_agent_types():
    with pytest.raises(ValidationError, match="request.agent_type"):
        AgentExecutionRequest(
            agent_type="planning",
            request=AgentRequest(
                project_id="demo",
                agent_type="coding",
                objective="Mismatch",
            ),
            config=AgentConfig(
                agent_type="planning",
                checkpoint_namespace="planning",
            ),
        )

    with pytest.raises(ValidationError, match="config.agent_type"):
        AgentExecutionRequest(
            agent_type="planning",
            request=AgentRequest(
                project_id="demo",
                agent_type="planning",
                objective="Mismatch",
            ),
            config=AgentConfig(
                agent_type="coding",
                checkpoint_namespace="coding",
            ),
        )


@pytest.mark.asyncio
async def test_flow_stops_at_configured_approval_gate():
    step_orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                "planning",
                next_action=AgentNextAction.REQUEST_APPROVAL,
                next_agent_type=None,
                requires_approval=True,
            )
        ]
    )
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=step_orchestrator,
    )

    result = await service.execute_flow(_execution("planning"))

    assert result.status == AgentFlowStatus.WAITING_FOR_APPROVAL
    assert len(result.steps) == 1
    assert result.pending_route.requires_approval is True


@pytest.mark.asyncio
async def test_flow_runs_planning_coding_and_verification_to_completion():
    step_orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                "planning",
                next_action=AgentNextAction.RUN_CODING,
                next_agent_type="coding",
            ),
            _outcome(
                "coding",
                next_action=AgentNextAction.RUN_VERIFICATION,
                next_agent_type="verification",
            ),
            _outcome(
                "verification",
                next_action=AgentNextAction.COMPLETE,
                next_agent_type=None,
            ),
        ]
    )
    resolver = InMemoryTransitionRequestResolver(
        [_execution("coding"), _execution("verification")]
    )
    flow = AgentFlowOrchestrator(
        step_orchestrator=step_orchestrator,
        transition_resolver=resolver,
    )

    result = await flow.run(_execution("planning"))

    assert result.status == AgentFlowStatus.COMPLETED
    assert [step.execution.agent_type for step in result.steps] == [
        "planning",
        "coding",
        "verification",
    ]
    assert result.final_outcome.result.agent_type == "verification"


@pytest.mark.asyncio
async def test_flow_routes_verification_changes_back_to_coding():
    step_orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                "verification",
                next_action=AgentNextAction.RUN_CODING,
                next_agent_type="coding",
            ),
            _outcome(
                "coding",
                next_action=AgentNextAction.COMPLETE,
                next_agent_type=None,
            ),
        ]
    )
    flow = AgentFlowOrchestrator(
        step_orchestrator=step_orchestrator,
        transition_resolver=InMemoryTransitionRequestResolver([_execution("coding")]),
    )

    result = await flow.run(_execution("verification"))

    assert result.status == AgentFlowStatus.COMPLETED
    assert [step.execution.agent_type for step in result.steps] == [
        "verification",
        "coding",
    ]


@pytest.mark.asyncio
async def test_flow_distinguishes_clarification_from_other_escalations():
    step_orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                "planning",
                next_action=AgentNextAction.REQUEST_CLARIFICATION,
                next_agent_type=None,
                escalate=True,
                status=AgentRunStatus.WAITING,
            )
        ]
    )

    result = await AgentFlowOrchestrator(step_orchestrator=step_orchestrator).run(
        _execution("planning")
    )

    assert result.status == AgentFlowStatus.WAITING_FOR_CLARIFICATION


@pytest.mark.asyncio
async def test_flow_returns_transition_pending_without_typed_next_request():
    step_orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                "coding",
                next_action=AgentNextAction.RUN_VERIFICATION,
                next_agent_type="verification",
            )
        ]
    )

    result = await AgentFlowOrchestrator(step_orchestrator=step_orchestrator).run(
        _execution("coding")
    )

    assert result.status == AgentFlowStatus.TRANSITION_PENDING
    assert result.pending_route.next_agent_type == "verification"
    assert "typed verification request" in result.reason


@pytest.mark.asyncio
async def test_flow_rejects_cross_workflow_transition_request():
    step_orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                "coding",
                next_action=AgentNextAction.RUN_VERIFICATION,
                next_agent_type="verification",
            )
        ]
    )
    flow = AgentFlowOrchestrator(
        step_orchestrator=step_orchestrator,
        transition_resolver=InMemoryTransitionRequestResolver(
            [_execution("verification", workflow_id="other-workflow")]
        ),
    )

    result = await flow.run(_execution("coding"))

    assert result.status == AgentFlowStatus.ESCALATED
    assert result.reason == "Transition request must preserve workflow_id."


@pytest.mark.asyncio
async def test_flow_stops_retry_loop_at_step_limit():
    retry_outcome = _outcome(
        "coding",
        next_action=AgentNextAction.RETRY,
        next_agent_type="coding",
        status=AgentRunStatus.FAILED,
    )
    step_orchestrator = ScriptedStepOrchestrator([retry_outcome, retry_outcome])
    flow = AgentFlowOrchestrator(
        step_orchestrator=step_orchestrator,
        transition_resolver=InMemoryTransitionRequestResolver([_execution("coding")]),
    )

    result = await flow.run(_execution("coding"), max_steps=2)

    assert result.status == AgentFlowStatus.MAX_STEPS_EXCEEDED
    assert len(result.steps) == 2


def test_retry_route_targets_current_agent():
    route = route_transition(
        AgentTransition(
            next_action=AgentNextAction.RETRY,
            reason="Transient tool failure.",
        ),
        current_agent_type="coding",
    )

    assert route.next_action == AgentNextAction.RETRY
    assert route.next_agent_type == "coding"
    assert route.escalate is False
