from __future__ import annotations

import asyncio
from datetime import timedelta
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowApproval,
    AgentFlowResult,
    AgentFlowStatus,
    AgentFlowStep,
    AgentFlowVersionConflictError,
    AgentOrchestrationResult,
    AgentRouteDecision,
    PersistedAgentResult,
)
from agent_core.domain.enums import ApprovalDecision
from agent_core.models import AgentPlatformFlowRecord
from agent_core.persistence.agent_flows import SqlAlchemyAgentFlowStore


POSTGRES_URL_ENV = "PHASE3_POSTGRES_DATABASE_URL"


@pytest.fixture(scope="module")
def migrated_postgres_url() -> str:
    database_url = os.getenv(POSTGRES_URL_ENV)
    if not database_url:
        pytest.skip(f"Set {POSTGRES_URL_ENV} to run live agent-flow integration tests")

    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root / "agent_core"
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=package_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return database_url


def _execution(
    agent_type: str,
    *,
    project_id: str,
    workflow_id: str,
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        workflow_id=workflow_id,
        agent_type=agent_type,
        request=AgentRequest(
            project_id=project_id,
            task_id="task.postgres-flow",
            agent_type=agent_type,
            objective=f"Run {agent_type}.",
        ),
        config=AgentConfig(
            agent_type=agent_type,
            checkpoint_namespace=agent_type,
        ),
        correlation_id="postgres-flow-correlation",
    )


def _flow_result(
    execution: AgentExecutionRequest,
    *,
    status: AgentFlowStatus,
    next_action: AgentNextAction,
    requires_approval: bool = False,
) -> AgentFlowResult:
    result = AgentResult(
        execution_id=execution.request.execution_id,
        project_id=execution.request.project_id,
        task_id=execution.request.task_id,
        agent_type=execution.agent_type,
        status=AgentRunStatus.SUCCEEDED,
        summary=f"{execution.agent_type} completed.",
        next_action=next_action,
    )
    route = AgentRouteDecision(
        next_action=next_action,
        next_agent_type=None,
        requires_approval=requires_approval,
        escalate=False,
        reason=f"Route after {execution.agent_type}.",
    )
    outcome = AgentOrchestrationResult(
        result=result,
        persisted=PersistedAgentResult(result_id=uuid4(), result=result),
        route=route,
    )
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
        pending_route=route,
        reason=route.reason,
    )


@pytest.mark.asyncio
async def test_postgres_flow_store_persists_versioned_resume_history(
    migrated_postgres_url: str,
):
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = f"flow-project-{uuid4()}"
    workflow_id = f"flow-workflow-{uuid4()}"

    try:
        async with session_factory() as session:
            store = SqlAlchemyAgentFlowStore(session)
            planning = _execution(
                "planning",
                project_id=project_id,
                workflow_id=workflow_id,
            )
            reserved = await store.reserve(planning)
            waiting = await store.complete_run(
                flow_id=reserved.flow_id,
                result=_flow_result(
                    planning,
                    status=AgentFlowStatus.WAITING_FOR_APPROVAL,
                    next_action=AgentNextAction.REQUEST_APPROVAL,
                    requires_approval=True,
                ),
                expected_version=reserved.version,
                lease_id=reserved.lease.lease_id,
            )

            approval = AgentFlowApproval(
                decision=ApprovalDecision.APPROVED,
                approval_reference="postgres-approval-1",
                actor="integration-test",
            )
            coding = _execution(
                "coding",
                project_id=project_id,
                workflow_id=workflow_id,
            )
            resumed = await store.begin_resume(
                flow_id=waiting.flow_id,
                execution=coding,
                expected_version=waiting.version,
                approval=approval,
            )
            completed = await store.complete_run(
                flow_id=resumed.flow_id,
                result=_flow_result(
                    coding,
                    status=AgentFlowStatus.COMPLETED,
                    next_action=AgentNextAction.COMPLETE,
                ),
                expected_version=resumed.version,
                lease_id=resumed.lease.lease_id,
            )

            reloaded = await store.get(completed.flow_id)
            assert reloaded is not None
            assert reloaded.status == AgentFlowStatus.COMPLETED
            assert reloaded.version == 4
            assert reloaded.resume_count == 1
            assert reloaded.step_count == 2
            assert [step.agent_type for step in reloaded.steps] == [
                "planning",
                "coding",
            ]
            assert reloaded.approvals == [approval]

            record = await session.get(AgentPlatformFlowRecord, completed.flow_id)
            assert record is not None
            assert record.status == AgentFlowStatus.COMPLETED.value
            assert record.version == 4
            assert record.step_count == 2
            assert record.current_agent_type == "coding"
            assert record.pending_agent_type is None
            assert record.requires_approval is False
            assert record.lease_id is None
            assert record.last_approval_decision == ApprovalDecision.APPROVED.value

            with pytest.raises(
                AgentFlowVersionConflictError,
                match="expected 2, found 4",
            ):
                await store.begin_resume(
                    flow_id=completed.flow_id,
                    execution=coding,
                    expected_version=2,
                )
            assert session.in_transaction() is False

            recovery_execution = _execution(
                "planning",
                project_id=project_id,
                workflow_id=f"{workflow_id}-recovery",
            )
            recovery_reserved = await store.reserve(
                recovery_execution,
                lease_owner="postgres-worker-1",
                lease_seconds=60,
            )
            heartbeat_at = recovery_reserved.lease.acquired_at + timedelta(seconds=30)
            heartbeat = await store.renew_lease(
                flow_id=recovery_reserved.flow_id,
                lease_id=recovery_reserved.lease.lease_id,
                expected_version=recovery_reserved.version,
                lease_seconds=120,
                now=heartbeat_at,
            )
            recovered = await store.claim_recovery(
                flow_id=heartbeat.flow_id,
                execution=recovery_execution,
                expected_version=heartbeat.version,
                recovered_by="postgres-worker-2",
                lease_seconds=300,
                now=heartbeat.lease.expires_at,
            )
            recovery_completed = await store.complete_run(
                flow_id=recovered.flow_id,
                result=_flow_result(
                    recovery_execution,
                    status=AgentFlowStatus.COMPLETED,
                    next_action=AgentNextAction.COMPLETE,
                ),
                expected_version=recovered.version,
                lease_id=recovered.lease.lease_id,
            )

            assert recovery_completed.version == 3
            assert recovery_completed.recovery_count == 1
            assert recovery_completed.lease is None
            by_workflow = await store.get_by_workflow(
                project_id=project_id,
                workflow_id=recovery_execution.workflow_id,
            )
            assert by_workflow == recovery_completed

            recovery_record = await session.get(
                AgentPlatformFlowRecord,
                recovery_completed.flow_id,
            )
            assert recovery_record is not None
            assert recovery_record.recovery_count == 1
            assert recovery_record.lease_id is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_flow_queue_claims_distinct_rows_concurrently(
    migrated_postgres_url: str,
):
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = f"flow-queue-project-{uuid4()}"
    executions = [
        _execution(
            "planning",
            project_id=project_id,
            workflow_id=f"flow-queue-workflow-{uuid4()}",
        )
        for _ in range(2)
    ]

    async def claim_next():
        async with session_factory() as session:
            return await SqlAlchemyAgentFlowStore(session).claim_next(
                worker_id=f"postgres-worker-{uuid4()}",
                lease_seconds=60,
            )

    try:
        async with session_factory() as session:
            store = SqlAlchemyAgentFlowStore(session)
            queued = [
                await store.enqueue(execution, max_steps=index + 3)
                for index, execution in enumerate(executions)
            ]
            assert [flow.status for flow in queued] == [
                AgentFlowStatus.QUEUED,
                AgentFlowStatus.QUEUED,
            ]
            assert [flow.execution_options.max_steps for flow in queued] == [3, 4]

        claims = await asyncio.gather(claim_next(), claim_next())

        assert all(claim is not None for claim in claims)
        claimed = [claim for claim in claims if claim is not None]
        assert len({claim.flow_id for claim in claimed}) == 2
        assert {claim.flow_id for claim in claimed} == {flow.flow_id for flow in queued}
        assert all(claim.status == AgentFlowStatus.RUNNING for claim in claimed)
        assert all(claim.version == 2 for claim in claimed)

        execution_by_workflow = {
            execution.workflow_id: execution for execution in executions
        }
        for claim in claimed:
            async with session_factory() as session:
                completed = await SqlAlchemyAgentFlowStore(session).complete_run(
                    flow_id=claim.flow_id,
                    result=_flow_result(
                        execution_by_workflow[claim.workflow_id],
                        status=AgentFlowStatus.COMPLETED,
                        next_action=AgentNextAction.COMPLETE,
                    ),
                    expected_version=claim.version,
                    lease_id=claim.lease.lease_id,
                )
                assert completed.status == AgentFlowStatus.COMPLETED
    finally:
        await engine.dispose()
