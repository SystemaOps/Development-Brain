from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentResult,
    AgentRunStatus,
)
from agent_core.agent_platform.agents.coding import CodingAgentRequest
from agent_core.agent_platform.agents.planning import PlanningAgentRequest
from agent_core.agent_platform.adapters.openproject import (
    ManagedWorkPackageGateway,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.orchestration import (
    AgentFlowApproval,
    AgentFlowLeaseConflictError,
    AgentFlowVersionConflictError,
    AgentOrchestrationResult,
    AgentRouteDecision,
    PersistedAgentResult,
)
from agent_core.api.agents import (
    AgentExecutePayload,
    AgentFlowHeartbeatPayload,
    AgentFlowRecoveryPayload,
    AgentFlowResumePayload,
    AgentFlowStartPayload,
    AgentVerificationOverridePayload,
    create_agent_platform_service_for_db,
    enqueue_agent_flow,
    execute_agent,
    get_agent_flow_by_workflow,
    heartbeat_agent_flow,
    override_agent_verification,
    recover_agent_flow,
    router,
    resume_agent_flow,
    start_agent_flow,
)
from agent_core.domain.coding import CodingAttemptRequest, FileChange
from agent_core.domain.enums import ApprovalDecision
from agent_core.persistence.agent_flows import SqlAlchemyAgentFlowStore
from agent_core.services.agent_transition_resolver import (
    ApplicationAgentTransitionResolver,
)


class FakeAgentPlatformService:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        result = AgentResult(
            execution_id=request.request.execution_id,
            project_id=request.request.project_id,
            task_id=request.request.task_id,
            agent_type=request.agent_type,
            status=AgentRunStatus.SUCCEEDED,
            summary="Agent execution completed.",
            next_action=AgentNextAction.COMPLETE,
        )
        return AgentOrchestrationResult(
            result=result,
            persisted=PersistedAgentResult(result_id=uuid4(), result=result),
            route=AgentRouteDecision(
                next_agent_type=None,
                requires_approval=False,
                escalate=False,
                reason="Agent completed.",
            ),
        )


class FakeFlowService:
    def __init__(self) -> None:
        self.calls = []
        self.current = SimpleNamespace(
            workflow_id="stored-workflow",
            correlation_id="stored-correlation",
            pending_execution_payload={
                "config": AgentConfig(
                    agent_type="planning",
                    checkpoint_namespace="planning",
                ).model_dump(mode="json")
            },
        )

    async def start_flow(self, execution, **kwargs):
        self.calls.append(("start", execution, kwargs))
        return "started"

    async def enqueue_flow(self, execution, **kwargs):
        self.calls.append(("enqueue", execution, kwargs))
        return "queued"

    async def get_flow(self, flow_id):
        self.calls.append(("get", flow_id))
        return self.current

    async def get_flow_by_workflow(self, **kwargs):
        self.calls.append(("get_by_workflow", kwargs))
        return self.current

    async def heartbeat_flow(self, **kwargs):
        self.calls.append(("heartbeat", kwargs))
        return "heartbeat"

    async def recover_flow(self, **kwargs):
        self.calls.append(("recover", kwargs))
        return "recovered"

    async def resume_flow(self, **kwargs):
        self.calls.append(("resume", kwargs))
        return "resumed"

    async def override_verification_flow(self, **kwargs):
        self.calls.append(("verification_override", kwargs))
        return "overridden"


def test_agent_flow_operational_routes_are_registered_before_dynamic_lookup():
    paths = [route.path for route in router.routes]

    assert "/v1/agents/flows/by-workflow" in paths
    assert "/v1/agents/flows/async" in paths
    assert "/v1/agents/flows/{flow_id}/heartbeat" in paths
    assert "/v1/agents/flows/{flow_id}/recover" in paths
    assert "/v1/agents/flows/{flow_id}/verification-override" in paths
    assert paths.index("/v1/agents/flows/by-workflow") < paths.index(
        "/v1/agents/flows/{flow_id}"
    )


def test_agent_execute_payload_discriminates_coding_request():
    payload = AgentExecutePayload.model_validate(
        {
            "request": {
                "agent_type": "coding",
                "project_id": "demo",
                "task_id": "task.sample",
                "objective": "Change one file.",
                "approved": True,
                "coding_attempt": {
                    "task_key": "task.sample",
                    "repository_key": "sample-project",
                    "file_changes": [
                        {
                            "relative_path": "src/app.py",
                            "content": "VALUE = 'new'\n",
                        }
                    ],
                },
            }
        }
    )

    assert isinstance(payload.request, CodingAgentRequest)
    assert payload.request.coding_attempt is not None
    assert payload.request.coding_attempt.repository_key == "sample-project"


def test_database_platform_service_includes_production_transition_resolver():
    db = object()

    service = create_agent_platform_service_for_db(db)

    assert isinstance(
        service.transition_resolver,
        ApplicationAgentTransitionResolver,
    )
    assert service.transition_resolver.context_store.db is db
    assert isinstance(service.flow_store, SqlAlchemyAgentFlowStore)
    assert service.flow_store.db is db
    assert isinstance(
        service.dependencies.work_package_gateway,
        ManagedWorkPackageGateway,
    )


def test_database_platform_service_accepts_injected_work_package_gateway():
    db = object()
    gateway = object()

    service = create_agent_platform_service_for_db(
        db,
        work_package_gateway=gateway,
    )

    assert service.dependencies.work_package_gateway is gateway


@pytest.mark.asyncio
async def test_execute_agent_uses_default_config_and_service(monkeypatch):
    fake_service = FakeAgentPlatformService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    payload = AgentExecutePayload(
        request=PlanningAgentRequest(
            project_id="demo",
            objective="Plan the modular agent platform.",
        ),
        workflow_id="workflow-api-test",
        correlation_id="correlation-api-test",
    )

    response = await execute_agent(payload, db=object())

    assert response.result.project_id == "demo"
    assert response.result.agent_type == "planning"
    assert response.persisted_result_id is not None
    assert fake_service.calls[0].workflow_id == "workflow-api-test"
    assert fake_service.calls[0].correlation_id == "correlation-api-test"
    assert fake_service.calls[0].config.agent_type == "planning"


@pytest.mark.asyncio
async def test_execute_agent_rejects_mismatched_config(monkeypatch):
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: FakeAgentPlatformService(),
    )
    payload = AgentExecutePayload(
        request=CodingAgentRequest(
            project_id="demo",
            task_id="task.sample",
            objective="Change one file.",
            approved=True,
            coding_attempt=CodingAttemptRequest(
                task_key="task.sample",
                repository_key="sample-project",
                file_changes=[
                    FileChange(relative_path="src/app.py", content="VALUE = 'new'\n")
                ],
            ),
        ),
        config=AgentConfig(agent_type="planning", checkpoint_namespace="planning"),
    )

    with pytest.raises(HTTPException) as exc:
        await execute_agent(payload, db=object())

    assert exc.value.status_code == 422
    assert "config.agent_type" in exc.value.detail


@pytest.mark.asyncio
async def test_start_agent_flow_builds_typed_execution_request(monkeypatch):
    fake_service = FakeFlowService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    payload = AgentFlowStartPayload(
        request=PlanningAgentRequest(
            project_id="demo",
            objective="Create a durable plan.",
        ),
        workflow_id="workflow-flow-api",
        correlation_id="correlation-flow-api",
        max_steps=4,
    )

    response = await start_agent_flow(payload, db=object())

    assert response == "started"
    _, execution, kwargs = fake_service.calls[0]
    assert execution.workflow_id == "workflow-flow-api"
    assert execution.correlation_id == "correlation-flow-api"
    assert execution.agent_type == "planning"
    assert kwargs == {"max_steps": 4}


@pytest.mark.asyncio
async def test_enqueue_agent_flow_builds_typed_execution_request(monkeypatch):
    fake_service = FakeFlowService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    payload = AgentFlowStartPayload(
        request=PlanningAgentRequest(
            project_id="demo",
            objective="Queue a durable plan.",
        ),
        workflow_id="workflow-queue-api",
        correlation_id="correlation-queue-api",
        max_steps=6,
    )

    response = await enqueue_agent_flow(payload, db=object())

    assert response == "queued"
    operation, execution, kwargs = fake_service.calls[0]
    assert operation == "enqueue"
    assert execution.workflow_id == "workflow-queue-api"
    assert execution.correlation_id == "correlation-queue-api"
    assert isinstance(execution.request, PlanningAgentRequest)
    assert kwargs == {"max_steps": 6}


@pytest.mark.asyncio
async def test_resume_agent_flow_uses_stored_workflow_identity(monkeypatch):
    fake_service = FakeFlowService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    flow_id = uuid4()
    payload = AgentFlowResumePayload(
        expected_version=2,
        request=PlanningAgentRequest(
            project_id="demo",
            objective="Resume after approval.",
        ),
        correlation_id="resume-correlation",
        approval=AgentFlowApproval(
            decision=ApprovalDecision.APPROVED,
            approval_reference="approval-api-1",
        ),
        max_steps=3,
    )

    response = await resume_agent_flow(flow_id, payload, db=object())

    assert response == "resumed"
    _, resume_kwargs = fake_service.calls[-1]
    assert resume_kwargs["flow_id"] == flow_id
    assert resume_kwargs["expected_version"] == 2
    assert resume_kwargs["request"].workflow_id == "stored-workflow"
    assert resume_kwargs["request"].correlation_id == "resume-correlation"
    assert resume_kwargs["approval"].approval_reference == "approval-api-1"
    assert resume_kwargs["max_steps"] == 3


@pytest.mark.asyncio
async def test_override_agent_verification_passes_typed_audit_command(monkeypatch):
    fake_service = FakeFlowService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    flow_id = uuid4()
    payload = AgentVerificationOverridePayload(
        expected_version=2,
        actor="reviewer@example.test",
        reason="Approved by change control.",
        override_reference="change-control-417",
        metadata={"ticket": "CC-417"},
    )

    response = await override_agent_verification(flow_id, payload, db=object())

    assert response == "overridden"
    operation, kwargs = fake_service.calls[-1]
    assert operation == "verification_override"
    assert kwargs["flow_id"] == flow_id
    assert kwargs["expected_version"] == 2
    assert kwargs["command"].actor == "reviewer@example.test"
    assert kwargs["command"].reason == "Approved by change control."
    assert kwargs["command"].override_reference == "change-control-417"
    assert kwargs["command"].metadata == {"ticket": "CC-417"}


@pytest.mark.asyncio
async def test_start_agent_flow_maps_version_conflict_to_http_409(monkeypatch):
    class ConflictingFlowService:
        async def start_flow(self, execution, **kwargs):
            del execution, kwargs
            raise AgentFlowVersionConflictError("workflow already exists")

    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: ConflictingFlowService(),
    )
    payload = AgentFlowStartPayload(
        request=PlanningAgentRequest(
            project_id="demo",
            objective="Create a durable plan.",
        )
    )

    with pytest.raises(HTTPException) as exc:
        await start_agent_flow(payload, db=object())

    assert exc.value.status_code == 409
    assert exc.value.detail == "workflow already exists"


@pytest.mark.asyncio
async def test_get_agent_flow_by_workflow_uses_project_identity(monkeypatch):
    fake_service = FakeFlowService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )

    response = await get_agent_flow_by_workflow(
        project_id="demo",
        workflow_id="stored-workflow",
        db=object(),
    )

    assert response is fake_service.current
    assert fake_service.calls[-1] == (
        "get_by_workflow",
        {"project_id": "demo", "workflow_id": "stored-workflow"},
    )


@pytest.mark.asyncio
async def test_heartbeat_agent_flow_passes_lease_claim(monkeypatch):
    fake_service = FakeFlowService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    flow_id = uuid4()
    lease_id = uuid4()

    response = await heartbeat_agent_flow(
        flow_id,
        AgentFlowHeartbeatPayload(
            expected_version=3,
            lease_id=lease_id,
        ),
        db=object(),
    )

    assert response == "heartbeat"
    _, kwargs = fake_service.calls[-1]
    assert kwargs == {
        "flow_id": flow_id,
        "lease_id": lease_id,
        "expected_version": 3,
    }


@pytest.mark.asyncio
async def test_recover_agent_flow_reuses_persisted_config_and_identity(monkeypatch):
    fake_service = FakeFlowService()
    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    flow_id = uuid4()
    execution_id = uuid4()
    payload = AgentFlowRecoveryPayload(
        expected_version=1,
        recovered_by="operator-api",
        request=PlanningAgentRequest(
            execution_id=execution_id,
            project_id="demo",
            objective="Recover exact planning execution.",
        ),
        max_steps=2,
    )

    response = await recover_agent_flow(flow_id, payload, db=object())

    assert response == "recovered"
    _, kwargs = fake_service.calls[-1]
    assert kwargs["flow_id"] == flow_id
    assert kwargs["expected_version"] == 1
    assert kwargs["recovered_by"] == "operator-api"
    assert kwargs["request"].workflow_id == "stored-workflow"
    assert kwargs["request"].correlation_id == "stored-correlation"
    assert kwargs["request"].request.execution_id == execution_id
    assert kwargs["request"].config.checkpoint_namespace == "planning"
    assert kwargs["max_steps"] == 2


@pytest.mark.asyncio
async def test_heartbeat_maps_active_lease_conflict_to_http_409(monkeypatch):
    class ConflictingLeaseService:
        async def heartbeat_flow(self, **kwargs):
            del kwargs
            raise AgentFlowLeaseConflictError("lease token does not match")

    monkeypatch.setattr(
        "agent_core.api.agents.create_agent_platform_service_for_db",
        lambda db: ConflictingLeaseService(),
    )

    with pytest.raises(HTTPException) as exc:
        await heartbeat_agent_flow(
            uuid4(),
            AgentFlowHeartbeatPayload(
                expected_version=1,
                lease_id=uuid4(),
            ),
            db=object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "lease token does not match"


@pytest.mark.asyncio
async def test_event_orchestrate_endpoint_uses_agent_platform_service(monkeypatch):
    from agent_core.api.events import orchestrate_event

    captured = {}
    fake_service = object()

    class FakeProjectEventOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def handle_persisted_event(self, event_id: str):
            captured["event_id"] = event_id
            return SimpleNamespace(as_dict=lambda: {"event_id": event_id, "ok": True})

    monkeypatch.setattr(
        "agent_core.api.events.create_agent_platform_service_for_db",
        lambda db: fake_service,
    )
    monkeypatch.setattr(
        "agent_core.api.events.SqlAlchemyEventInbox",
        lambda db: "inbox",
    )
    monkeypatch.setattr(
        "agent_core.api.events.SqlAlchemyAgentExecutionRecorder",
        lambda db: "recorder",
    )
    monkeypatch.setattr(
        "agent_core.api.events.ProjectEventOrchestrator",
        FakeProjectEventOrchestrator,
    )

    response = await orchestrate_event("event-1", db=object())

    assert response == {"event_id": "event-1", "ok": True}
    assert captured["event_inbox"] == "inbox"
    assert captured["execution_recorder"] == "recorder"
    assert captured["agent_platform_service"] is fake_service
    assert "planning_runner" not in captured
