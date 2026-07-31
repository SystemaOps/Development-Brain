from __future__ import annotations

from uuid import uuid4

import pytest

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentResult,
    AgentRunStatus,
    ArtifactReference,
    StateReference,
)
from agent_core.agent_platform.agents.base.errors import (
    AgentConfigurationError,
)
from agent_core.agent_platform.agents.coding import (
    CodingAgentRequest,
    CodingAgentResult,
)
from agent_core.agent_platform.agents.planning import (
    PlanningAgentRequest,
    PlanningAgentResult,
)
from agent_core.agent_platform.agents.verification import (
    VerificationAgentRequest,
    VerificationAgentResult,
    VerificationFinding,
    VerificationVerdict,
)
from agent_core.agent_platform.config import (
    AgentConfig,
    load_agent_platform_config,
)
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentOrchestrationResult,
    AgentRouteDecision,
    AgentTaskTransitionContext,
    PersistedAgentResult,
)
from agent_core.agent_platform.runtime import AgentDependencyContainer
from agent_core.domain.coding import (
    CodingAttemptRequest,
    CodingAttemptResult,
    FileChange,
    RollbackPlan,
)
from agent_core.domain.enums import CodingAttemptStatus, PlanNodeKind
from agent_core.schemas import (
    AcceptanceCriterionSpec,
    PlanNodeSpec,
    ProjectPlanSpec,
)
from agent_core.services.agent_transition_resolver import (
    ApplicationAgentTransitionResolver,
)
from agent_core.services.agent_platform_service import AgentPlatformService


class FakeTransitionContextStore:
    def __init__(self, context: AgentTaskTransitionContext | None) -> None:
        self.context = context
        self.calls: list[dict[str, str]] = []

    async def load_task_context(
        self,
        *,
        project_id: str,
        task_id: str,
        workflow_id: str,
        plan_version_id: str | None = None,
    ) -> AgentTaskTransitionContext | None:
        self.calls.append(
            {
                "project_id": project_id,
                "task_id": task_id,
                "workflow_id": workflow_id,
                "plan_version_id": plan_version_id,
            }
        )
        return self.context


class FakeCodingService:
    def __init__(self, result: CodingAttemptResult) -> None:
        self.result = result
        self.calls: list[tuple[str, CodingAttemptRequest]] = []

    async def run_explicit_attempt(
        self,
        *,
        project_key: str,
        request: CodingAttemptRequest,
    ) -> CodingAttemptResult:
        self.calls.append((project_key, request))
        return self.result


def _acceptance_criterion() -> AcceptanceCriterionSpec:
    return AcceptanceCriterionSpec(
        key="ac.task",
        statement="Transitions are enabled in the application.",
        verification_method="unit_test",
    )


def _plan(*, task_count: int = 1) -> ProjectPlanSpec:
    nodes = [
        PlanNodeSpec(
            stable_key="vision.platform",
            kind=PlanNodeKind.VISION,
            title="Platform",
            objective="Build the platform.",
        ),
        PlanNodeSpec(
            stable_key="capability.runtime",
            kind=PlanNodeKind.CAPABILITY,
            title="Runtime",
            objective="Build the runtime.",
            parent_stable_key="vision.platform",
        ),
        PlanNodeSpec(
            stable_key="epic.agents",
            kind=PlanNodeKind.EPIC,
            title="Agents",
            objective="Build the agents.",
            parent_stable_key="capability.runtime",
        ),
        PlanNodeSpec(
            stable_key="story.transitions",
            kind=PlanNodeKind.STORY,
            title="Transitions",
            objective="Build transitions.",
            parent_stable_key="epic.agents",
        ),
    ]
    nodes.extend(
        PlanNodeSpec(
            stable_key=f"task.transition-{index}",
            kind=PlanNodeKind.TASK,
            title=f"Transition {index}",
            objective=f"Implement transition {index}.",
            parent_stable_key="story.transitions",
            acceptance_criteria=[_acceptance_criterion()],
        )
        for index in range(1, task_count + 1)
    )
    return ProjectPlanSpec(summary="Implement transitions.", nodes=nodes)


def _coding_attempt() -> CodingAttemptRequest:
    return CodingAttemptRequest(
        task_key="task.transition-1",
        repository_key="sample-project",
        file_changes=[
            FileChange(
                relative_path="src/app.py",
                content="TRANSITIONS_ENABLED = True\n",
            )
        ],
    )


def _coding_result() -> CodingAttemptResult:
    return CodingAttemptResult(
        task_key="task.transition-1",
        repository_key="sample-project",
        attempt_number=1,
        status=CodingAttemptStatus.SUCCEEDED,
        changed_files=["src/app.py"],
        final_diff="+TRANSITIONS_ENABLED = True\n",
        rollback_plan=RollbackPlan(
            available=True,
            strategy="reverse_diff",
            changed_files=["src/app.py"],
        ),
    )


def _context(**updates) -> AgentTaskTransitionContext:
    values = {
        "task_id": "task.transition-1",
        "objective": "Implement transition 1.",
        "acceptance_criteria": [_acceptance_criterion()],
        "input_artifacts": [
            ArtifactReference(
                artifact_id="context-1",
                artifact_type="context_capsule",
                uri="postgres://context_capsules/context-1",
            )
        ],
        "planning_approved": True,
        "prepared_coding_attempt": _coding_attempt(),
        "latest_coding_result": _coding_result(),
        "metadata": {"plan_version_id": "plan-1"},
    }
    values.update(updates)
    return AgentTaskTransitionContext.model_validate(values)


def _execution(request, *, approval_required: bool = False) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        workflow_id="workflow-transition",
        agent_type=request.agent_type,
        request=request,
        config=AgentConfig(
            agent_type=request.agent_type,
            checkpoint_namespace=request.agent_type,
            approval_required=approval_required,
        ),
        correlation_id="correlation-transition",
    )


def _outcome(result, next_agent_type: str, next_action: AgentNextAction):
    return AgentOrchestrationResult(
        result=result,
        persisted=PersistedAgentResult(result=result),
        route=AgentRouteDecision(
            next_action=next_action,
            next_agent_type=next_agent_type,
            requires_approval=False,
            escalate=False,
            reason="Continue flow.",
        ),
    )


def _resolver(context: AgentTaskTransitionContext | None):
    store = FakeTransitionContextStore(context)
    resolver = ApplicationAgentTransitionResolver(
        context_store=store,
        config=load_agent_platform_config(),
    )
    return resolver, store


@pytest.mark.asyncio
async def test_resolver_builds_approved_coding_request_from_planning_context():
    planning_request = PlanningAgentRequest(
        project_id="demo",
        objective="Plan transitions.",
        plan=_plan(),
    )
    planning_result = PlanningAgentResult(
        execution_id=planning_request.execution_id,
        project_id="demo",
        agent_type="planning",
        status=AgentRunStatus.SUCCEEDED,
        summary="Planning completed.",
        next_action=AgentNextAction.RUN_CODING,
        plan=_plan(),
    )
    previous = _execution(planning_request, approval_required=True)
    outcome = _outcome(
        planning_result,
        "coding",
        AgentNextAction.RUN_CODING,
    )
    resolver, store = _resolver(_context())

    execution = await resolver.resolve_next(
        previous_execution=previous,
        previous_outcome=outcome,
        route=outcome.route,
    )

    assert execution is not None
    assert isinstance(execution.request, CodingAgentRequest)
    assert execution.workflow_id == previous.workflow_id
    assert execution.request.approved is True
    assert execution.request.coding_attempt == _coding_attempt()
    assert execution.request.input_artifacts[0].artifact_id == "context-1"
    assert store.calls == [
        {
            "project_id": "demo",
            "task_id": "task.transition-1",
            "workflow_id": "workflow-transition",
            "plan_version_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_resolver_does_not_invent_missing_coding_attempt_or_approval():
    planning_request = PlanningAgentRequest(
        project_id="demo",
        objective="Plan transitions.",
        plan=_plan(),
    )
    planning_result = PlanningAgentResult(
        execution_id=planning_request.execution_id,
        project_id="demo",
        agent_type="planning",
        status=AgentRunStatus.SUCCEEDED,
        summary="Planning completed.",
        next_action=AgentNextAction.RUN_CODING,
        plan=_plan(),
    )
    previous = _execution(planning_request, approval_required=True)
    outcome = _outcome(planning_result, "coding", AgentNextAction.RUN_CODING)

    missing_attempt, _ = _resolver(_context(prepared_coding_attempt=None))
    missing_approval, _ = _resolver(_context(planning_approved=False))

    assert (
        await missing_attempt.resolve_next(
            previous_execution=previous,
            previous_outcome=outcome,
            route=outcome.route,
        )
        is None
    )
    assert (
        await missing_approval.resolve_next(
            previous_execution=previous,
            previous_outcome=outcome,
            route=outcome.route,
        )
        is None
    )


@pytest.mark.asyncio
async def test_resolver_rejects_coding_attempt_for_another_task():
    planning_request = PlanningAgentRequest(
        project_id="demo",
        objective="Plan transitions.",
        plan=_plan(),
    )
    planning_result = PlanningAgentResult(
        execution_id=planning_request.execution_id,
        project_id="demo",
        agent_type="planning",
        status=AgentRunStatus.SUCCEEDED,
        summary="Planning completed.",
        next_action=AgentNextAction.RUN_CODING,
        plan=_plan(),
    )
    wrong_attempt = _coding_attempt().model_copy(update={"task_key": "task.other"})
    resolver, _ = _resolver(_context(prepared_coding_attempt=wrong_attempt))
    previous = _execution(planning_request, approval_required=True)
    outcome = _outcome(planning_result, "coding", AgentNextAction.RUN_CODING)

    with pytest.raises(AgentConfigurationError, match="task_key"):
        await resolver.resolve_next(
            previous_execution=previous,
            previous_outcome=outcome,
            route=outcome.route,
        )


@pytest.mark.asyncio
async def test_resolver_builds_verification_from_coding_result_and_acceptance_criteria():
    coding_request = CodingAgentRequest(
        project_id="demo",
        task_id="task.transition-1",
        objective="Implement transition 1.",
        approved=True,
        coding_attempt=_coding_attempt(),
        metadata={
            "transition_context": {
                "plan_version_id": "00000000-0000-0000-0000-000000000001"
            }
        },
    )
    coding_result = CodingAgentResult(
        execution_id=coding_request.execution_id,
        project_id="demo",
        task_id="task.transition-1",
        agent_type="coding",
        status=AgentRunStatus.SUCCEEDED,
        summary="Coding completed.",
        next_action=AgentNextAction.RUN_VERIFICATION,
        coding_result=_coding_result(),
    )
    previous = _execution(coding_request)
    outcome = _outcome(
        coding_result,
        "verification",
        AgentNextAction.RUN_VERIFICATION,
    )
    resolver, store = _resolver(_context())

    execution = await resolver.resolve_next(
        previous_execution=previous,
        previous_outcome=outcome,
        route=outcome.route,
    )

    assert execution is not None
    assert isinstance(execution.request, VerificationAgentRequest)
    assert execution.request.coding_result == _coding_result()
    assert execution.request.repository_diff == _coding_result().final_diff
    assert execution.request.acceptance_criteria == [_acceptance_criterion()]
    assert execution.config.agent_type == "verification"
    assert store.calls[0]["plan_version_id"] == ("00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
async def test_database_ready_resolver_drives_coding_to_verification_completion():
    coding_service = FakeCodingService(_coding_result())
    resolver, _ = _resolver(_context())
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(coding_service=coding_service),
        transition_resolver=resolver,
    )
    coding_request = CodingAgentRequest(
        project_id="demo",
        task_id="task.transition-1",
        objective="Implement transition 1.",
        approved=True,
        coding_attempt=_coding_attempt(),
    )

    result = await service.execute_flow(
        _execution(coding_request),
        max_steps=3,
    )

    assert result.status.value == "completed"
    assert [step.execution.agent_type for step in result.steps] == [
        "coding",
        "verification",
    ]
    assert isinstance(result.final_outcome.result, VerificationAgentResult)
    assert result.final_outcome.result.verdict == VerificationVerdict.PASSED
    assert coding_service.calls == [("demo", _coding_attempt())]


@pytest.mark.asyncio
async def test_resolver_requires_explicit_rework_attempt_after_verification():
    verification_request = VerificationAgentRequest(
        project_id="demo",
        task_id="task.transition-1",
        objective="Verify transition 1.",
        coding_result=_coding_result(),
    )
    verification_result = VerificationAgentResult(
        execution_id=verification_request.execution_id,
        project_id="demo",
        task_id="task.transition-1",
        agent_type="verification",
        status=AgentRunStatus.FAILED,
        summary="Changes requested.",
        next_action=AgentNextAction.RUN_CODING,
        verdict=VerificationVerdict.CHANGES_REQUESTED,
        findings=[
            VerificationFinding(
                severity="error",
                code="acceptance_criterion_unmet",
                message="Add coverage.",
            )
        ],
    )
    previous = _execution(verification_request)
    outcome = _outcome(
        verification_result,
        "coding",
        AgentNextAction.RUN_CODING,
    )
    no_rework, _ = _resolver(_context(latest_coding_attempt=_coding_attempt()))
    with_rework, _ = _resolver(
        _context(
            prepared_rework_attempt=_coding_attempt(),
            latest_coding_attempt=_coding_attempt(),
        )
    )

    assert (
        await no_rework.resolve_next(
            previous_execution=previous,
            previous_outcome=outcome,
            route=outcome.route,
        )
        is None
    )
    execution = await with_rework.resolve_next(
        previous_execution=previous,
        previous_outcome=outcome,
        route=outcome.route,
    )
    assert execution is not None
    assert isinstance(execution.request, CodingAgentRequest)
    assert execution.request.metadata["verification_findings"][0]["code"] == (
        "acceptance_criterion_unmet"
    )


@pytest.mark.asyncio
async def test_resolver_retries_same_typed_request_with_new_execution_identity():
    coding_request = CodingAgentRequest(
        project_id="demo",
        task_id="task.transition-1",
        objective="Implement transition 1.",
        approved=True,
        coding_attempt=_coding_attempt(),
    )
    state = StateReference(
        namespace="coding",
        key="workflow-transition:coding",
        checkpoint_id="checkpoint-1",
    )
    failed_result = CodingAgentResult(
        execution_id=coding_request.execution_id,
        project_id="demo",
        task_id="task.transition-1",
        agent_type="coding",
        status=AgentRunStatus.FAILED,
        summary="Transient failure.",
        next_action=AgentNextAction.RETRY,
        state=state,
    )
    previous = _execution(coding_request)
    outcome = _outcome(failed_result, "coding", AgentNextAction.RETRY)
    resolver, store = _resolver(None)

    execution = await resolver.resolve_next(
        previous_execution=previous,
        previous_outcome=outcome,
        route=outcome.route,
    )

    assert execution is not None
    assert isinstance(execution.request, CodingAgentRequest)
    assert execution.request.execution_id != coding_request.execution_id
    assert execution.request.coding_attempt == coding_request.coding_attempt
    assert execution.request.state == state
    assert execution.request.metadata["retry_of_execution_id"] == str(
        coding_request.execution_id
    )
    assert store.calls == []


@pytest.mark.asyncio
async def test_resolver_leaves_multi_task_plan_pending_without_explicit_task():
    planning_request = PlanningAgentRequest(
        project_id="demo",
        objective="Plan transitions.",
        plan=_plan(task_count=2),
    )
    planning_result = PlanningAgentResult(
        execution_id=planning_request.execution_id,
        project_id="demo",
        agent_type="planning",
        status=AgentRunStatus.SUCCEEDED,
        summary="Planning completed.",
        next_action=AgentNextAction.RUN_CODING,
        plan=_plan(task_count=2),
    )
    previous = _execution(planning_request, approval_required=False)
    outcome = _outcome(planning_result, "coding", AgentNextAction.RUN_CODING)
    resolver, store = _resolver(_context())

    execution = await resolver.resolve_next(
        previous_execution=previous,
        previous_outcome=outcome,
        route=outcome.route,
    )

    assert execution is None
    assert store.calls == []


@pytest.mark.asyncio
async def test_resolver_can_route_explicit_replanning_without_task_context():
    result = AgentResult(
        execution_id=uuid4(),
        project_id="demo",
        task_id="task.transition-1",
        agent_type="verification",
        status=AgentRunStatus.BLOCKED,
        summary="Requirements conflict.",
        next_action=AgentNextAction.RUN_PLANNING,
    )
    previous = _execution(
        VerificationAgentRequest(
            project_id="demo",
            task_id="task.transition-1",
            objective="Verify transition 1.",
            coding_result=_coding_result(),
        )
    )
    outcome = _outcome(result, "planning", AgentNextAction.RUN_PLANNING)
    resolver, store = _resolver(None)

    execution = await resolver.resolve_next(
        previous_execution=previous,
        previous_outcome=outcome,
        route=outcome.route,
    )

    assert execution is not None
    assert isinstance(execution.request, PlanningAgentRequest)
    assert execution.request.task_id == "task.transition-1"
    assert store.calls == []
