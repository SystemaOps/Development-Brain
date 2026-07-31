from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_core.agent_platform.agents.base import AgentNextAction, AgentRequest, AgentResult, AgentRunStatus, BaseAgent
from agent_core.agent_platform.agents.base.errors import AgentValidationError
from agent_core.agent_platform.agents.coding import CodingAgentRequest, CodingAgentResult
from agent_core.agent_platform.agents.planning import PlanningAgentRequest, PlanningAgentResult
from agent_core.agent_platform.agents.verification import (
    VerificationAgentRequest,
    VerificationAgentResult,
    VerificationVerdict,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.factory import AgentBuilderRegistry, AgentFactory, create_default_agent_factory
from agent_core.agent_platform.orchestration import AgentExecutionRequest, AgentOrchestrator
from agent_core.agent_platform.runtime import AgentDependencyContainer, CheckpointIdentity, InMemoryAgentEventBus, InMemoryCheckpointStore
from agent_core.domain.coding import CodingAttemptRequest, CodingAttemptResult, FileChange, RollbackPlan
from agent_core.domain.enums import CodingAttemptStatus, PlanNodeKind
from agent_core.schemas import AcceptanceCriterionSpec, PlanNodeSpec, ProjectPlanSpec


class FakeCodingService:
    def __init__(self, result: CodingAttemptResult | None = None) -> None:
        self.result = result or _coding_result()
        self.calls: list[tuple[str, CodingAttemptRequest]] = []

    async def run_explicit_attempt(self, *, project_key: str, request: CodingAttemptRequest) -> CodingAttemptResult:
        self.calls.append((project_key, request))
        return self.result


class CapturingResultStore:
    def __init__(self) -> None:
        self.results: list[AgentResult] = []

    async def persist(self, result: AgentResult):
        from agent_core.agent_platform.orchestration import PersistedAgentResult

        self.results.append(result)
        return PersistedAgentResult(result=result)


class DummyAgent(BaseAgent):
    @property
    def agent_type(self) -> str:
        return "dummy"

    async def initialize(self) -> None:
        return None

    async def execute(self, request, context):
        return AgentResult(
            execution_id=request.execution_id,
            agent_type=self.agent_type,
            status=AgentRunStatus.SUCCEEDED,
            summary="dummy completed",
        )

    async def validate_request(self, request) -> None:
        if request.agent_type != self.agent_type:
            raise AgentValidationError("wrong agent type")

    async def shutdown(self) -> None:
        return None


class DummyBuilder:
    @property
    def agent_type(self) -> str:
        return "dummy"

    def build(self, *, config: AgentConfig, dependencies: AgentDependencyContainer) -> BaseAgent:
        return DummyAgent()


class MismatchedBuilder(DummyBuilder):
    @property
    def agent_type(self) -> str:
        return "other"


def _plan() -> ProjectPlanSpec:
    return ProjectPlanSpec(
        summary="Add the agent platform foundation.",
        nodes=[
            PlanNodeSpec(
                stable_key="vision.agent-platform",
                kind=PlanNodeKind.VISION,
                title="Agent platform",
                objective="Create a modular agent platform.",
            ),
            PlanNodeSpec(
                stable_key="capability.agent-runtime",
                kind=PlanNodeKind.CAPABILITY,
                title="Agent runtime",
                objective="Provide factory and runtime contracts.",
                parent_stable_key="vision.agent-platform",
            ),
            PlanNodeSpec(
                stable_key="epic.agent-contracts",
                kind=PlanNodeKind.EPIC,
                title="Agent contracts",
                objective="Define stable contracts for agents.",
                parent_stable_key="capability.agent-runtime",
            ),
            PlanNodeSpec(
                stable_key="story.agent-contracts",
                kind=PlanNodeKind.STORY,
                title="Agent contract story",
                objective="Expose common contracts to every agent.",
                parent_stable_key="epic.agent-contracts",
            ),
            PlanNodeSpec(
                stable_key="task.agent-contracts",
                kind=PlanNodeKind.TASK,
                title="Implement contracts",
                objective="Add typed request and result contracts.",
                parent_stable_key="story.agent-contracts",
                acceptance_criteria=[
                    AcceptanceCriterionSpec(
                        key="ac.contracts",
                        statement="Typed request and result contracts exist for agent execution.",
                        verification_method="unit_test",
                    )
                ],
            ),
        ],
    )


def _coding_request() -> CodingAttemptRequest:
    return CodingAttemptRequest(
        task_key="task.agent-contracts",
        repository_key="demo-repo",
        file_changes=[FileChange(relative_path="src/platform.py", content="VALUE = 'new'\n")],
    )


def _coding_result(status: CodingAttemptStatus = CodingAttemptStatus.SUCCEEDED, diff: str | None = None) -> CodingAttemptResult:
    return CodingAttemptResult(
        task_key="task.agent-contracts",
        repository_key="demo-repo",
        attempt_number=1,
        status=status,
        changed_files=["src/platform.py"] if status != CodingAttemptStatus.BLOCKED else [],
        final_diff=diff if diff is not None else "+Typed request and result contracts exist for agent execution.\n",
        rollback_plan=RollbackPlan(available=True, strategy="reverse_diff", changed_files=["src/platform.py"]),
        errors=["repository conflict"] if status == CodingAttemptStatus.BLOCKED else [],
    )


def _context(agent_type: str, execution_id, checkpoint_store: InMemoryCheckpointStore | None = None):
    from agent_core.agent_platform.runtime import AgentExecutionContext

    checkpoint = CheckpointIdentity(
        project_id="demo",
        workflow_id="workflow-1",
        agent_type=agent_type,
        agent_instance_id=f"{agent_type}:default",
        execution_id=execution_id,
        thread_id=f"demo:task.agent-contracts:{agent_type}",
    )
    return AgentExecutionContext(
        execution_id=execution_id,
        project_id="demo",
        task_id="task.agent-contracts",
        workflow_id="workflow-1",
        agent_type=agent_type,
        agent_instance_id=f"{agent_type}:default",
        thread_id=checkpoint.thread_id,
        checkpoint=checkpoint,
        correlation_id="correlation-1",
    )


def test_factory_registration_and_creation_contracts():
    dependencies = AgentDependencyContainer(coding_service=FakeCodingService())
    factory = create_default_agent_factory(dependencies)

    assert factory.registry.names() == ["coding", "planning", "verification"]
    for agent_type in factory.registry.names():
        config = AgentConfig(agent_type=agent_type, checkpoint_namespace=agent_type)
        agent = factory.create(agent_type=agent_type, config=config)
        assert isinstance(agent, BaseAgent)
        assert agent.agent_type == agent_type

    verification_agent = factory.create(
        agent_type="verification",
        config=AgentConfig(
            agent_type="verification",
            checkpoint_namespace="verification",
            settings={"require_diff_for_pass": False},
        ),
    )
    assert verification_agent.config.require_diff_for_pass is False


def test_factory_rejects_duplicate_unknown_disabled_and_mismatched_builders():
    registry = AgentBuilderRegistry()
    registry.register("dummy", DummyBuilder())

    with pytest.raises(ValueError, match="already registered"):
        registry.register("dummy", DummyBuilder())
    with pytest.raises(KeyError, match="Unknown agent type"):
        registry.get("missing")
    with pytest.raises(ValueError, match="does not match"):
        AgentBuilderRegistry().register("dummy", MismatchedBuilder())

    factory = AgentFactory(dependencies=AgentDependencyContainer())
    factory.register("dummy", DummyBuilder())
    with pytest.raises(ValueError, match="disabled"):
        factory.create(agent_type="dummy", config=AgentConfig(agent_type="dummy", checkpoint_namespace="dummy", enabled=False))


def test_agent_request_contract_rejects_missing_required_fields():
    with pytest.raises(ValidationError):
        AgentRequest(agent_type="planning", objective="missing project")


def test_platform_persistence_models_are_registered():
    from agent_core.models import AgentPlatformCheckpointRecord, AgentPlatformResultRecord

    checkpoint_columns = AgentPlatformCheckpointRecord.__table__.columns
    result_columns = AgentPlatformResultRecord.__table__.columns

    assert {
        "project_key",
        "workflow_id",
        "agent_type",
        "agent_instance_id",
        "execution_id",
        "thread_id",
        "checkpoint_id",
        "state_json",
    } <= set(checkpoint_columns.keys())
    assert {
        "execution_id",
        "project_key",
        "task_key",
        "agent_type",
        "status",
        "next_action",
        "result_type",
        "result_json",
    } <= set(result_columns.keys())


@pytest.mark.asyncio
async def test_registered_agents_accept_valid_requests_and_produce_valid_results():
    checkpoint_store = InMemoryCheckpointStore()
    dependencies = AgentDependencyContainer(checkpoint_store=checkpoint_store, coding_service=FakeCodingService())
    factory = create_default_agent_factory(dependencies)

    planning_agent = factory.create(
        agent_type="planning",
        config=AgentConfig(agent_type="planning", checkpoint_namespace="planning", approval_required=True),
    )
    planning_request = PlanningAgentRequest(project_id="demo", objective="Implement typed agent contracts", plan=_plan())
    await planning_agent.validate_request(planning_request)
    planning_result = await planning_agent.execute(planning_request, _context("planning", planning_request.execution_id))
    assert isinstance(planning_result, PlanningAgentResult)
    assert AgentResult.model_validate(planning_result.model_dump(mode="json"))
    assert planning_result.status == AgentRunStatus.SUCCEEDED
    assert planning_result.next_action == AgentNextAction.REQUEST_APPROVAL

    coding_agent = factory.create(agent_type="coding", config=AgentConfig(agent_type="coding", checkpoint_namespace="coding"))
    coding_request = CodingAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Implement typed agent contracts",
        approved=True,
        coding_attempt=_coding_request(),
    )
    await coding_agent.validate_request(coding_request)
    coding_result = await coding_agent.execute(coding_request, _context("coding", coding_request.execution_id))
    assert isinstance(coding_result, CodingAgentResult)
    assert AgentResult.model_validate(coding_result.model_dump(mode="json"))
    assert coding_result.status == AgentRunStatus.SUCCEEDED
    assert coding_result.next_action == AgentNextAction.RUN_VERIFICATION

    verification_agent = factory.create(agent_type="verification", config=AgentConfig(agent_type="verification", checkpoint_namespace="verification"))
    verification_request = VerificationAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Verify typed agent contracts",
        acceptance_criteria=_plan().nodes[-1].acceptance_criteria,
        coding_result=_coding_result(),
    )
    await verification_agent.validate_request(verification_request)
    verification_result = await verification_agent.execute(
        verification_request,
        _context("verification", verification_request.execution_id),
    )
    assert isinstance(verification_result, VerificationAgentResult)
    assert AgentResult.model_validate(verification_result.model_dump(mode="json"))
    assert verification_result.verdict == VerificationVerdict.PASSED
    assert verification_result.next_action == AgentNextAction.COMPLETE
    assert verification_result.acceptance_coverage.total_count == 1
    assert verification_result.acceptance_coverage.mandatory_criteria_satisfied is True
    assert verification_result.security_review.passed is True
    assert verification_result.evidence_summary.diff_present is True


@pytest.mark.asyncio
async def test_agents_reject_invalid_requests():
    dependencies = AgentDependencyContainer(coding_service=FakeCodingService())
    factory = create_default_agent_factory(dependencies)
    wrong_request = AgentRequest(project_id="demo", task_id="task.agent-contracts", agent_type="wrong", objective="bad")

    for agent_type in ["planning", "coding", "verification"]:
        agent = factory.create(agent_type=agent_type, config=AgentConfig(agent_type=agent_type, checkpoint_namespace=agent_type))
        with pytest.raises(AgentValidationError):
            await agent.validate_request(wrong_request)


@pytest.mark.asyncio
async def test_orchestrator_routes_planning_to_configurable_approval_gate():
    event_bus = InMemoryAgentEventBus()
    dependencies = AgentDependencyContainer(event_bus=event_bus, coding_service=FakeCodingService())
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)
    request = PlanningAgentRequest(project_id="demo", objective="Plan the platform", plan=_plan())

    result = await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="planning",
            request=request,
            config=AgentConfig(agent_type="planning", checkpoint_namespace="planning", approval_required=True),
        )
    )

    assert result.result.status == AgentRunStatus.SUCCEEDED
    assert result.route.requires_approval is True
    assert result.route.next_agent_type is None
    assert [event.event_type.value for event in event_bus.events] == [
        "agent.created",
        "agent.started",
        "agent.step.started",
        "agent.step.completed",
        "agent.completed",
        "agent.result.persisted",
        "agent.transition.requested",
    ]


@pytest.mark.asyncio
async def test_orchestrator_routes_coding_to_verification():
    dependencies = AgentDependencyContainer(coding_service=FakeCodingService())
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)
    request = CodingAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Implement typed agent contracts",
        approved=True,
        coding_attempt=_coding_request(),
    )

    result = await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="coding",
            request=request,
            config=AgentConfig(agent_type="coding", checkpoint_namespace="coding"),
        )
    )

    assert result.route.next_agent_type == "verification"
    assert result.route.requires_approval is False


@pytest.mark.asyncio
async def test_orchestrator_uses_dependency_injected_result_store():
    result_store = CapturingResultStore()
    dependencies = AgentDependencyContainer(
        coding_service=FakeCodingService(),
        result_store=result_store,
    )
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)
    request = CodingAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Implement typed agent contracts",
        approved=True,
        coding_attempt=_coding_request(),
    )

    await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="coding",
            request=request,
            config=AgentConfig(agent_type="coding", checkpoint_namespace="coding"),
        )
    )

    assert len(result_store.results) == 1
    assert result_store.results[0].project_id == "demo"
    assert result_store.results[0].task_id == "task.agent-contracts"


@pytest.mark.asyncio
async def test_orchestrator_routes_verification_changes_requested_to_coding():
    dependencies = AgentDependencyContainer(coding_service=FakeCodingService())
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)
    request = VerificationAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Verify typed agent contracts",
        acceptance_criteria=[
            AcceptanceCriterionSpec(
                key="ac.unmet",
                statement="The payment gateway retries transient failures.",
                verification_method="unit_test",
            )
        ],
        coding_result=_coding_result(diff="+Typed contracts exist.\n"),
    )

    result = await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="verification",
            request=request,
            config=AgentConfig(agent_type="verification", checkpoint_namespace="verification"),
        )
    )

    assert isinstance(result.result, VerificationAgentResult)
    assert result.result.verdict == VerificationVerdict.CHANGES_REQUESTED
    assert result.route.next_agent_type == "coding"


@pytest.mark.asyncio
async def test_orchestrator_routes_verification_blocked_to_escalation():
    dependencies = AgentDependencyContainer(coding_service=FakeCodingService())
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)
    request = VerificationAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Verify typed agent contracts",
        coding_result=_coding_result(CodingAttemptStatus.BLOCKED, diff=""),
    )

    result = await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="verification",
            request=request,
            config=AgentConfig(agent_type="verification", checkpoint_namespace="verification"),
        )
    )

    assert result.result.status == AgentRunStatus.BLOCKED
    assert result.route.escalate is True
    assert result.result.errors[0].category.value == "blocked_error"


@pytest.mark.asyncio
async def test_planning_ambiguity_requires_clarification():
    dependencies = AgentDependencyContainer(coding_service=FakeCodingService())
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)
    request = PlanningAgentRequest(
        project_id="demo",
        objective="Implement it",
        clarification_required=True,
    )

    result = await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="planning",
            request=request,
            config=AgentConfig(agent_type="planning", checkpoint_namespace="planning", approval_required=False),
        )
    )

    assert result.result.status == AgentRunStatus.WAITING
    assert result.result.next_action == AgentNextAction.REQUEST_CLARIFICATION
    assert result.route.escalate is True


@pytest.mark.asyncio
async def test_coding_conflict_returns_blocked_without_calling_another_agent():
    blocked_service = FakeCodingService(result=_coding_result(CodingAttemptStatus.BLOCKED, diff=""))
    dependencies = AgentDependencyContainer(coding_service=blocked_service)
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)
    request = CodingAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Implement typed agent contracts",
        approved=True,
        coding_attempt=_coding_request(),
    )

    result = await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="coding",
            request=request,
            config=AgentConfig(agent_type="coding", checkpoint_namespace="coding"),
        )
    )

    assert result.result.status == AgentRunStatus.BLOCKED
    assert result.route.escalate is True
    assert blocked_service.calls


@pytest.mark.asyncio
async def test_checkpoint_namespaces_are_agent_scoped_and_failures_are_preserved():
    checkpoint_store = InMemoryCheckpointStore()
    dependencies = AgentDependencyContainer(checkpoint_store=checkpoint_store, coding_service=FakeCodingService())
    orchestrator = AgentOrchestrator(factory=create_default_agent_factory(dependencies), dependencies=dependencies)

    planning_request = PlanningAgentRequest(project_id="demo", objective="Plan the platform", plan=_plan())
    coding_request = CodingAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Implement typed agent contracts",
        approved=True,
        coding_attempt=_coding_request(),
    )
    failed_request = CodingAgentRequest(
        project_id="demo",
        task_id="task.agent-contracts",
        objective="Implement typed agent contracts",
        approved=False,
        coding_attempt=_coding_request(),
    )

    await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="planning",
            request=planning_request,
            config=AgentConfig(agent_type="planning", checkpoint_namespace="planning"),
        )
    )
    await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="coding",
            request=coding_request,
            config=AgentConfig(agent_type="coding", checkpoint_namespace="coding"),
        )
    )
    failed = await orchestrator.run_once(
        AgentExecutionRequest(
            agent_type="coding",
            request=failed_request,
            config=AgentConfig(agent_type="coding", checkpoint_namespace="coding"),
        )
    )

    namespaces = checkpoint_store.namespaces()
    assert any(namespace[2] == "planning" for namespace in namespaces)
    assert any(namespace[2] == "coding" for namespace in namespaces)
    assert failed.result.status == AgentRunStatus.FAILED
    assert failed.result.state is not None
    assert failed.result.errors[0].category.value == "validation_error"
