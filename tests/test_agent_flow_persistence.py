from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from agent_core.agent_platform.agents.base.errors import AgentValidationError
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowApproval,
    AgentFlowLeaseConflictError,
    AgentFlowPersistenceError,
    AgentFlowResult,
    AgentFlowStatus,
    AgentFlowStep,
    AgentFlowVersionConflictError,
    AgentOrchestrationResult,
    AgentRouteDecision,
    InMemoryAgentFlowStore,
    PersistedAgentResult,
)
from agent_core.agent_platform.runtime import AgentDependencyContainer
from agent_core.domain.enums import ApprovalDecision
from agent_core.services.agent_platform_service import AgentPlatformService


class ScriptedStepOrchestrator:
    def __init__(
        self,
        outcomes: list[AgentOrchestrationResult | Exception],
    ) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[AgentExecutionRequest] = []

    async def run_once(
        self,
        execution: AgentExecutionRequest,
    ) -> AgentOrchestrationResult:
        self.calls.append(execution)
        if not self.outcomes:
            raise AssertionError("No scripted outcome remains")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _execution(
    agent_type: str = "planning",
    *,
    workflow_id: str = "durable-workflow",
    project_id: str = "demo",
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        workflow_id=workflow_id,
        agent_type=agent_type,
        request=AgentRequest(
            project_id=project_id,
            task_id="task-1",
            agent_type=agent_type,
            objective=f"Run {agent_type}.",
        ),
        config=AgentConfig(
            agent_type=agent_type,
            checkpoint_namespace=agent_type,
        ),
        correlation_id="durable-correlation",
    )


def _outcome(
    execution: AgentExecutionRequest,
    *,
    next_action: AgentNextAction,
    next_agent_type: str | None,
    requires_approval: bool = False,
) -> AgentOrchestrationResult:
    result = AgentResult(
        execution_id=execution.request.execution_id,
        project_id=execution.request.project_id,
        task_id=execution.request.task_id,
        agent_type=execution.agent_type,
        status=AgentRunStatus.SUCCEEDED,
        summary=f"{execution.agent_type} completed.",
        next_action=next_action,
    )
    return AgentOrchestrationResult(
        result=result,
        persisted=PersistedAgentResult(result_id=uuid4(), result=result),
        route=AgentRouteDecision(
            next_action=next_action,
            next_agent_type=next_agent_type,
            requires_approval=requires_approval,
            escalate=False,
            reason=f"Route after {execution.agent_type}.",
        ),
    )


def _flow_result(
    execution: AgentExecutionRequest,
    outcome: AgentOrchestrationResult,
    *,
    status: AgentFlowStatus,
) -> AgentFlowResult:
    return AgentFlowResult(
        workflow_id=execution.workflow_id,
        status=status,
        steps=[
            AgentFlowStep(
                sequence=1,
                execution=execution,
                outcome=outcome,
            )
        ],
        final_outcome=outcome,
        pending_route=outcome.route,
        reason=outcome.route.reason,
    )


def _approval(
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
) -> AgentFlowApproval:
    return AgentFlowApproval(
        decision=decision,
        approval_reference="approval-1",
        actor="reviewer@example.test",
        reason="Reviewed durable flow.",
    )


@pytest.mark.asyncio
async def test_in_memory_store_reserves_before_appending_completed_step():
    store = InMemoryAgentFlowStore()
    execution = _execution()

    reserved = await store.reserve(execution)

    assert reserved.status == AgentFlowStatus.RUNNING
    assert reserved.version == 1
    assert reserved.step_count == 0
    assert reserved.pending_execution_payload["request"]["execution_id"] == str(
        execution.request.execution_id
    )

    outcome = _outcome(
        execution,
        next_action=AgentNextAction.REQUEST_APPROVAL,
        next_agent_type=None,
        requires_approval=True,
    )
    completed = await store.complete_run(
        flow_id=reserved.flow_id,
        result=_flow_result(
            execution,
            outcome,
            status=AgentFlowStatus.WAITING_FOR_APPROVAL,
        ),
        expected_version=reserved.version,
        lease_id=reserved.lease.lease_id,
    )

    assert completed.status == AgentFlowStatus.WAITING_FOR_APPROVAL
    assert completed.version == 2
    assert completed.step_count == 1
    assert completed.pending_execution_payload is None
    assert completed.lease is None
    assert completed.steps[0].request_payload["agent_type"] == "planning"
    assert completed.steps[0].result_payload["summary"] == "planning completed."


@pytest.mark.asyncio
async def test_service_enqueues_claims_and_executes_background_flow():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    outcome = _outcome(
        execution,
        next_action=AgentNextAction.COMPLETE,
        next_agent_type=None,
    )
    orchestrator = ScriptedStepOrchestrator([outcome])
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=orchestrator,
        flow_store=store,
    )

    queued = await service.enqueue_flow(execution, max_steps=7)

    assert queued.status == AgentFlowStatus.QUEUED
    assert queued.version == 1
    assert queued.lease is None
    assert queued.execution_options.max_steps == 7
    assert orchestrator.calls == []

    claim = await store.claim_next(worker_id="background-worker")
    assert claim is not None
    assert claim.status == AgentFlowStatus.RUNNING
    assert claim.version == 2
    assert claim.lease.owner == "background-worker"

    completed = await service.execute_claimed_flow(
        claim=claim,
        request=execution,
        max_steps=claim.execution_options.max_steps,
    )

    assert completed.status == AgentFlowStatus.COMPLETED
    assert completed.version == 3
    assert completed.step_count == 1
    assert completed.lease is None
    assert orchestrator.calls == [execution]


@pytest.mark.asyncio
async def test_claim_next_honors_recovery_policy_and_escalates_exhausted_flow():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    reserved = await store.reserve(execution, lease_seconds=60)
    expired_at = reserved.lease.expires_at

    disabled = await store.claim_next(
        worker_id="background-worker",
        recover_expired=False,
        now=expired_at,
    )
    assert disabled is None

    exhausted = await store.claim_next(
        worker_id="background-worker",
        max_recovery_attempts=0,
        now=expired_at,
    )
    assert exhausted is None

    escalated = await store.get(reserved.flow_id)
    assert escalated is not None
    assert escalated.status == AgentFlowStatus.ESCALATED
    assert escalated.version == 2
    assert escalated.lease is None
    assert escalated.pending_execution_payload == reserved.pending_execution_payload
    assert "human intervention" in escalated.reason


@pytest.mark.asyncio
async def test_claim_next_uses_oldest_first_order_across_queue_and_recovery():
    store = InMemoryAgentFlowStore()
    abandoned_execution = _execution(workflow_id="abandoned-workflow")
    abandoned = await store.reserve(abandoned_execution, lease_seconds=60)
    await store.enqueue(_execution(workflow_id="new-queued-workflow"))

    claimed = await store.claim_next(
        worker_id="recovery-worker",
        now=abandoned.lease.expires_at,
    )

    assert claimed is not None
    assert claimed.flow_id == abandoned.flow_id
    assert claimed.recovery_count == 1
    assert claimed.lease.owner == "recovery-worker"


@pytest.mark.asyncio
async def test_in_memory_store_rejects_duplicate_workflow_and_stale_version():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    reserved = await store.reserve(execution)

    with pytest.raises(
        AgentFlowVersionConflictError,
        match="already exists",
    ):
        await store.reserve(execution)

    with pytest.raises(
        AgentFlowVersionConflictError,
        match="expected 2, found 1",
    ):
        await store.begin_resume(
            flow_id=reserved.flow_id,
            execution=execution,
            expected_version=2,
        )

    with pytest.raises(
        AgentFlowPersistenceError,
        match="cannot resume from status",
    ):
        await store.begin_resume(
            flow_id=reserved.flow_id,
            execution=execution,
            expected_version=reserved.version,
        )


@pytest.mark.asyncio
async def test_service_persists_approval_resume_and_append_only_history():
    store = InMemoryAgentFlowStore()
    planning_execution = _execution("planning")
    coding_execution = _execution("coding")
    orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                planning_execution,
                next_action=AgentNextAction.REQUEST_APPROVAL,
                next_agent_type=None,
                requires_approval=True,
            ),
            _outcome(
                coding_execution,
                next_action=AgentNextAction.COMPLETE,
                next_agent_type=None,
            ),
        ]
    )
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=orchestrator,
        flow_store=store,
    )

    waiting = await service.start_flow(planning_execution)
    completed = await service.resume_flow(
        flow_id=waiting.flow_id,
        expected_version=waiting.version,
        request=coding_execution,
        approval=_approval(),
    )

    assert completed.status == AgentFlowStatus.COMPLETED
    assert completed.version == 4
    assert completed.resume_count == 1
    assert completed.step_count == 2
    assert [step.sequence for step in completed.steps] == [1, 2]
    assert [step.agent_type for step in completed.steps] == ["planning", "coding"]
    assert completed.approvals[0].decision == ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_service_closes_rejected_approval_without_running_an_agent():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    orchestrator = ScriptedStepOrchestrator(
        [
            _outcome(
                execution,
                next_action=AgentNextAction.REQUEST_APPROVAL,
                next_agent_type=None,
                requires_approval=True,
            )
        ]
    )
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=orchestrator,
        flow_store=store,
    )

    waiting = await service.start_flow(execution)
    closed = await service.resume_flow(
        flow_id=waiting.flow_id,
        expected_version=waiting.version,
        approval=_approval(ApprovalDecision.CHANGES_REQUESTED),
    )

    assert closed.status == AgentFlowStatus.CHANGES_REQUESTED
    assert closed.version == 3
    assert closed.resume_count == 1
    assert len(orchestrator.calls) == 1


@pytest.mark.asyncio
async def test_service_requires_approval_and_typed_resume_request():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=ScriptedStepOrchestrator(
            [
                _outcome(
                    execution,
                    next_action=AgentNextAction.REQUEST_APPROVAL,
                    next_agent_type=None,
                    requires_approval=True,
                )
            ]
        ),
        flow_store=store,
    )
    waiting = await service.start_flow(execution)

    with pytest.raises(AgentValidationError, match="Approval evidence"):
        await service.resume_flow(
            flow_id=waiting.flow_id,
            expected_version=waiting.version,
            request=_execution("coding"),
        )

    with pytest.raises(AgentValidationError, match="typed execution request"):
        await service.resume_flow(
            flow_id=waiting.flow_id,
            expected_version=waiting.version,
            approval=_approval(),
        )


@pytest.mark.asyncio
async def test_service_preserves_reserved_execution_when_agent_raises():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=ScriptedStepOrchestrator([RuntimeError("tool failed")]),
        flow_store=store,
    )

    with pytest.raises(RuntimeError, match="tool failed"):
        await service.start_flow(execution)

    assert len(store.flows) == 1
    reserved = next(iter(store.flows.values()))
    assert reserved.status == AgentFlowStatus.RUNNING
    assert reserved.version == 1
    assert reserved.pending_execution_payload["request"]["execution_id"] == str(
        execution.request.execution_id
    )
    assert reserved.lease is not None


@pytest.mark.asyncio
async def test_heartbeat_extends_active_lease_without_changing_version():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    reserved = await store.reserve(execution, lease_seconds=60)
    renewed_at = reserved.lease.acquired_at + timedelta(seconds=30)

    heartbeat = await store.renew_lease(
        flow_id=reserved.flow_id,
        lease_id=reserved.lease.lease_id,
        expected_version=reserved.version,
        lease_seconds=120,
        now=renewed_at,
    )

    assert heartbeat.version == reserved.version
    assert heartbeat.lease.lease_id == reserved.lease.lease_id
    assert heartbeat.lease.expires_at == renewed_at + timedelta(seconds=120)

    with pytest.raises(AgentFlowLeaseConflictError, match="token does not match"):
        await store.renew_lease(
            flow_id=reserved.flow_id,
            lease_id=uuid4(),
            expected_version=reserved.version,
            now=renewed_at,
        )

    with pytest.raises(AgentFlowLeaseConflictError, match="token does not match"):
        await store.complete_run(
            flow_id=reserved.flow_id,
            result=_flow_result(
                execution,
                _outcome(
                    execution,
                    next_action=AgentNextAction.COMPLETE,
                    next_agent_type=None,
                ),
                status=AgentFlowStatus.COMPLETED,
            ),
            expected_version=reserved.version,
            lease_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_recovery_rejects_active_lease_and_modified_request():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    reserved = await store.reserve(execution, lease_seconds=60)

    with pytest.raises(AgentFlowLeaseConflictError, match="lease is active"):
        await store.claim_recovery(
            flow_id=reserved.flow_id,
            execution=execution,
            expected_version=reserved.version,
            recovered_by="worker-recovery",
            now=reserved.lease.acquired_at + timedelta(seconds=30),
        )

    with pytest.raises(AgentFlowLeaseConflictError, match="cannot complete"):
        await store.complete_run(
            flow_id=reserved.flow_id,
            result=_flow_result(
                execution,
                _outcome(
                    execution,
                    next_action=AgentNextAction.COMPLETE,
                    next_agent_type=None,
                ),
                status=AgentFlowStatus.COMPLETED,
            ),
            expected_version=reserved.version,
            lease_id=reserved.lease.lease_id,
            now=reserved.lease.expires_at,
        )

    modified = _execution()
    modified.request.execution_id = execution.request.execution_id
    modified.request.objective = "Silently expanded recovery scope."
    with pytest.raises(AgentFlowPersistenceError, match="exactly match"):
        await store.claim_recovery(
            flow_id=reserved.flow_id,
            execution=modified,
            expected_version=reserved.version,
            recovered_by="worker-recovery",
            now=reserved.lease.expires_at,
        )


@pytest.mark.asyncio
async def test_recovery_claim_replaces_expired_lease_and_records_audit():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    reserved = await store.reserve(execution, lease_seconds=60)

    recovered = await store.claim_recovery(
        flow_id=reserved.flow_id,
        execution=execution,
        expected_version=reserved.version,
        recovered_by="worker-recovery",
        lease_seconds=300,
        now=reserved.lease.expires_at,
    )

    assert recovered.version == 2
    assert recovered.recovery_count == 1
    assert recovered.lease.lease_id != reserved.lease.lease_id
    assert recovered.lease.owner == "worker-recovery"
    assert recovered.recoveries[0].previous_lease == reserved.lease
    assert recovered.recoveries[0].replacement_lease == recovered.lease

    with pytest.raises(AgentFlowVersionConflictError, match="expected 1, found 2"):
        await store.complete_run(
            flow_id=reserved.flow_id,
            result=_flow_result(
                execution,
                _outcome(
                    execution,
                    next_action=AgentNextAction.COMPLETE,
                    next_agent_type=None,
                ),
                status=AgentFlowStatus.COMPLETED,
            ),
            expected_version=reserved.version,
            lease_id=reserved.lease.lease_id,
        )


@pytest.mark.asyncio
async def test_service_recovers_failed_start_and_workflow_lookup():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    orchestrator = ScriptedStepOrchestrator([RuntimeError("worker stopped")])
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=orchestrator,
        flow_store=store,
        flow_lease_seconds=60,
    )

    with pytest.raises(RuntimeError, match="worker stopped"):
        await service.start_flow(execution)

    reserved = await service.get_flow_by_workflow(
        project_id=execution.request.project_id,
        workflow_id=execution.workflow_id,
    )
    store.flows[reserved.flow_id] = reserved.model_copy(
        update={
            "lease": reserved.lease.model_copy(
                update={
                    "expires_at": reserved.lease.acquired_at,
                }
            )
        }
    )
    orchestrator.outcomes.append(
        _outcome(
            execution,
            next_action=AgentNextAction.COMPLETE,
            next_agent_type=None,
        )
    )

    recovered = await service.recover_flow(
        flow_id=reserved.flow_id,
        expected_version=reserved.version,
        request=execution,
        recovered_by="operator-1",
    )

    assert recovered.status == AgentFlowStatus.COMPLETED
    assert recovered.version == 3
    assert recovered.recovery_count == 1
    assert recovered.step_count == 1


@pytest.mark.asyncio
async def test_service_can_disable_recovery():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    reserved = await store.reserve(execution)
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        flow_store=store,
        flow_recovery_enabled=False,
    )

    with pytest.raises(AgentValidationError, match="recovery is disabled"):
        await service.recover_flow(
            flow_id=reserved.flow_id,
            expected_version=reserved.version,
            request=execution,
            recovered_by="operator-1",
        )
