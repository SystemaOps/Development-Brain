from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from agent_core.agent_platform.agents.coding import CodingAgentRequest
from agent_core.agent_platform.agents.planning import PlanningAgentRequest
from agent_core.agent_platform.agents.verification import (
    VerificationAgentRequest,
    VerificationVerdict,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.factory import create_default_agent_factory
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentOrchestrator,
)
from agent_core.agent_platform.runtime import (
    AgentDependencyContainer,
    AgentExecutionContext,
    CheckpointIdentity,
    InMemoryCheckpointStore,
)
from agent_core.domain.coding import (
    CodingAttemptRequest,
    CodingAttemptResult,
    FileChange,
    RollbackPlan,
)
from agent_core.domain.enums import CodingAttemptStatus


class RecordingCheckpointStore(InMemoryCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[str, dict]] = []

    async def save(self, *, identity: CheckpointIdentity, state):
        self.records.append((identity.agent_type, deepcopy(state)))
        return await super().save(identity=identity, state=state)


class SuccessfulCodingService:
    async def run_explicit_attempt(
        self,
        *,
        project_key: str,
        request: CodingAttemptRequest,
    ) -> CodingAttemptResult:
        del project_key
        return _coding_result(request=request)


class FailingPlanningService:
    async def draft_plan(self, session_id: UUID):
        del session_id
        raise RuntimeError("planning backend unavailable")


def _coding_request() -> CodingAttemptRequest:
    return CodingAttemptRequest(
        task_key="task.internal-workflow",
        repository_key="demo-repository",
        file_changes=[
            FileChange(
                relative_path="src/workflow.py",
                content="WORKFLOW = 'independent'\n",
            )
        ],
    )


def _coding_result(
    *,
    request: CodingAttemptRequest | None = None,
) -> CodingAttemptResult:
    attempt = request or _coding_request()
    return CodingAttemptResult(
        task_key=attempt.task_key,
        repository_key=attempt.repository_key,
        attempt_number=1,
        status=CodingAttemptStatus.SUCCEEDED,
        changed_files=["src/workflow.py"],
        final_diff="+WORKFLOW = 'independent'\n",
        rollback_plan=RollbackPlan(
            available=True,
            strategy="reverse_diff",
            changed_files=["src/workflow.py"],
        ),
    )


def _context(agent_type: str, execution_id: UUID) -> AgentExecutionContext:
    checkpoint = CheckpointIdentity(
        project_id="demo",
        workflow_id="internal-workflow",
        agent_type=agent_type,
        agent_instance_id=f"{agent_type}:default",
        execution_id=execution_id,
        thread_id=f"demo:task.internal-workflow:{agent_type}",
    )
    return AgentExecutionContext(
        execution_id=execution_id,
        project_id="demo",
        task_id="task.internal-workflow",
        workflow_id="internal-workflow",
        agent_type=agent_type,
        agent_instance_id=f"{agent_type}:default",
        thread_id=checkpoint.thread_id,
        checkpoint=checkpoint,
        correlation_id="internal-workflow-correlation",
    )


def _agent(factory, agent_type: str):
    return factory.create(
        agent_type=agent_type,
        config=AgentConfig(
            agent_type=agent_type,
            checkpoint_namespace=agent_type,
        ),
    )


def test_registered_agents_compile_independent_internal_graphs():
    factory = create_default_agent_factory(AgentDependencyContainer())
    planning = _agent(factory, "planning")
    coding = _agent(factory, "coding")
    verification = _agent(factory, "verification")

    planning_nodes = set(planning.workflow.graph.get_graph().nodes)
    coding_nodes = set(coding.workflow.graph.get_graph().nodes)
    verification_nodes = set(verification.workflow.graph.get_graph().nodes)

    assert planning.workflow.graph.name == "planning-agent-workflow"
    assert coding.workflow.graph.name == "coding-agent-workflow"
    assert verification.workflow.graph.name == "verification-agent-workflow"
    assert "extract_requirements" in planning_nodes
    assert "execute_coding_attempt" in coding_nodes
    assert "evaluate_acceptance_criteria" in verification_nodes
    assert "execute_coding_attempt" not in planning_nodes
    assert "return_verdict" not in coding_nodes
    assert (
        len(
            {
                id(planning.workflow.graph),
                id(coding.workflow.graph),
                id(verification.workflow.graph),
            }
        )
        == 3
    )


@pytest.mark.asyncio
async def test_agent_graphs_persist_independent_phase_checkpoints():
    checkpoint_store = RecordingCheckpointStore()
    dependencies = AgentDependencyContainer(
        checkpoint_store=checkpoint_store,
        coding_service=SuccessfulCodingService(),
    )
    factory = create_default_agent_factory(dependencies)

    planning = _agent(factory, "planning")
    planning_request = PlanningAgentRequest(
        project_id="demo",
        objective="Clarify this task.",
        clarification_required=True,
    )
    planning_result = await planning.execute(
        planning_request,
        _context("planning", planning_request.execution_id),
    )

    coding = _agent(factory, "coding")
    coding_request = CodingAgentRequest(
        project_id="demo",
        task_id="task.internal-workflow",
        objective="Implement the independent workflow.",
        approved=True,
        coding_attempt=_coding_request(),
    )
    coding_result = await coding.execute(
        coding_request,
        _context("coding", coding_request.execution_id),
    )

    verification = _agent(factory, "verification")
    verification_request = VerificationAgentRequest(
        project_id="demo",
        task_id="task.internal-workflow",
        objective="Verify the independent workflow.",
        coding_result=_coding_result(),
    )
    verification_result = await verification.execute(
        verification_request,
        _context("verification", verification_request.execution_id),
    )

    final_states = {agent_type: state for agent_type, state in checkpoint_store.records}
    assert planning_result.state.namespace == "planning"
    assert coding_result.state.namespace == "coding"
    assert verification_result.state.namespace == "verification"
    assert final_states["planning"]["workflow_trace"] == [
        "extract_requirements",
        "waiting_for_clarification",
        "finalize",
    ]
    assert final_states["coding"]["workflow_trace"] == [
        "load_task_context",
        "execute_coding_attempt",
        "finalize",
    ]
    assert final_states["verification"]["workflow_trace"] == [
        "load_evidence",
        "inspect_result",
        "inspect_quality_commands",
        "evaluate_acceptance_criteria",
        "review_risk",
        "review_security_configuration",
        "return_verdict",
    ]
    assert verification_result.verdict == VerificationVerdict.PASSED
    assert {namespace[2] for namespace in checkpoint_store.namespaces()} == {
        "planning",
        "coding",
        "verification",
    }


@pytest.mark.asyncio
async def test_agent_failure_checkpoint_retains_last_completed_workflow_state():
    checkpoint_store = RecordingCheckpointStore()
    dependencies = AgentDependencyContainer(
        checkpoint_store=checkpoint_store,
        planning_service=FailingPlanningService(),
    )
    orchestrator = AgentOrchestrator(
        factory=create_default_agent_factory(dependencies),
        dependencies=dependencies,
    )
    request = PlanningAgentRequest(
        project_id="demo",
        objective="Generate a plan through the failing backend.",
        session_id=uuid4(),
    )

    outcome = await orchestrator.run_once(
        AgentExecutionRequest(
            workflow_id="failed-internal-workflow",
            agent_type="planning",
            request=request,
            config=AgentConfig(
                agent_type="planning",
                checkpoint_namespace="planning",
            ),
        )
    )

    assert outcome.result.status.value == "failed"
    failure_state = checkpoint_store.records[-1][1]
    assert failure_state["phase"] == "failed"
    assert failure_state["last_workflow_state"]["phase"] == "requirement_extraction"
    assert failure_state["last_workflow_state"]["workflow_trace"] == [
        "extract_requirements"
    ]
