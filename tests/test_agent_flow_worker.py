from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentResult,
    AgentRunStatus,
)
from agent_core.agent_platform.agents.planning import PlanningAgentRequest
from agent_core.agent_platform.config import (
    AgentConfig,
    AgentFlowRuntimeConfig,
    load_agent_platform_config,
)
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowStatus,
    AgentOrchestrationResult,
    AgentRouteDecision,
    InMemoryAgentFlowStore,
    PersistedAgentResult,
)
from agent_core.agent_platform.runtime import AgentDependencyContainer
from agent_core.services.agent_execution_codec import (
    AgentExecutionCodecError,
    AgentExecutionRequestCodec,
    create_default_agent_execution_codec,
)
from agent_core.services.agent_platform_service import AgentPlatformService
from agent_core.workers.agent_flow_worker import AgentFlowWorker


def _execution() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        workflow_id="background-workflow",
        agent_type="planning",
        request=PlanningAgentRequest(
            project_id="demo",
            task_id="task.background",
            objective="Execute a queued planning task.",
        ),
        config=AgentConfig(
            agent_type="planning",
            checkpoint_namespace="planning",
        ),
        correlation_id="background-correlation",
    )


def _outcome(execution: AgentExecutionRequest) -> AgentOrchestrationResult:
    result = AgentResult(
        execution_id=execution.request.execution_id,
        project_id=execution.request.project_id,
        task_id=execution.request.task_id,
        agent_type=execution.agent_type,
        status=AgentRunStatus.SUCCEEDED,
        summary="Background execution completed.",
        next_action=AgentNextAction.COMPLETE,
    )
    return AgentOrchestrationResult(
        result=result,
        persisted=PersistedAgentResult(result_id=uuid4(), result=result),
        route=AgentRouteDecision(
            next_action=AgentNextAction.COMPLETE,
            next_agent_type=None,
            requires_approval=False,
            escalate=False,
            reason="Background execution completed.",
        ),
    )


class DelayedOrchestrator:
    def __init__(self, *, delay_seconds: float = 0.04) -> None:
        self.delay_seconds = delay_seconds
        self.cancelled = asyncio.Event()
        self.calls: list[AgentExecutionRequest] = []

    async def run_once(
        self,
        execution: AgentExecutionRequest,
    ) -> AgentOrchestrationResult:
        self.calls.append(execution)
        try:
            await asyncio.sleep(self.delay_seconds)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return _outcome(execution)


class TrackingSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[object] = []

    def __call__(self):
        @asynccontextmanager
        async def context():
            session = object()
            self.sessions.append(session)
            yield session

        return context()


class FailingHeartbeatStore(InMemoryAgentFlowStore):
    async def renew_lease(self, **kwargs):
        del kwargs
        raise RuntimeError("heartbeat persistence failed")


def _worker(
    *,
    store: InMemoryAgentFlowStore,
    orchestrator: DelayedOrchestrator,
    session_factory: TrackingSessionFactory,
) -> AgentFlowWorker:
    service = AgentPlatformService(
        dependencies=AgentDependencyContainer(),
        orchestrator=orchestrator,
        flow_store=store,
    )
    return AgentFlowWorker(
        session_factory=session_factory,
        service_builder=lambda session: service,
        flow_store_factory=lambda session: store,
        worker_id="worker-test",
        lease_seconds=1,
        heartbeat_seconds=0.01,
        poll_seconds=0.01,
    )


def test_execution_codec_uses_registered_typed_request():
    execution = _execution()

    decoded = create_default_agent_execution_codec().decode(
        execution.model_dump(mode="json")
    )

    assert decoded == execution
    assert isinstance(decoded.request, PlanningAgentRequest)


def test_execution_codec_rejects_duplicate_unknown_and_malformed_payloads():
    codec = AgentExecutionRequestCodec()
    codec.register("planning", PlanningAgentRequest)

    with pytest.raises(AgentExecutionCodecError, match="already registered"):
        codec.register("planning", PlanningAgentRequest)

    with pytest.raises(AgentExecutionCodecError, match="Unknown"):
        codec.decode({"agent_type": "security_review"})

    malformed = _execution().model_dump(mode="json")
    malformed.pop("workflow_id")
    with pytest.raises(AgentExecutionCodecError, match="workflow_id"):
        codec.decode(malformed)


def test_flow_runtime_config_validates_heartbeat_and_recovery_policy():
    config = AgentFlowRuntimeConfig(
        lease_seconds=30,
        heartbeat_seconds=10,
        worker_poll_seconds=1,
        recovery_enabled=False,
        max_recovery_attempts=0,
    )

    assert config.recovery_enabled is False
    assert config.max_recovery_attempts == 0

    with pytest.raises(ValidationError, match="heartbeat_seconds"):
        AgentFlowRuntimeConfig(
            lease_seconds=30,
            heartbeat_seconds=30,
        )


def test_platform_config_loader_uses_environment_path(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-platform.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "planning": {
                        "agent_type": "planning",
                        "checkpoint_namespace": "planning",
                    }
                },
                "flow_runtime": {
                    "lease_seconds": 45,
                    "heartbeat_seconds": 15,
                    "worker_poll_seconds": 0.5,
                    "recovery_enabled": False,
                    "max_recovery_attempts": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_PLATFORM_CONFIG_FILE", str(config_path))

    loaded = load_agent_platform_config()

    assert loaded.flow_runtime.lease_seconds == 45
    assert loaded.flow_runtime.recovery_enabled is False
    assert loaded.flow_runtime.max_recovery_attempts == 0


@pytest.mark.asyncio
async def test_worker_claims_executes_and_heartbeats_in_independent_sessions():
    store = InMemoryAgentFlowStore()
    execution = _execution()
    await store.enqueue(execution, max_steps=4)
    orchestrator = DelayedOrchestrator()
    session_factory = TrackingSessionFactory()
    worker = _worker(
        store=store,
        orchestrator=orchestrator,
        session_factory=session_factory,
    )

    completed = await worker.run_once()

    assert completed is not None
    assert completed.status == AgentFlowStatus.COMPLETED
    assert completed.execution_options.max_steps == 4
    assert orchestrator.calls == [execution]
    assert len(session_factory.sessions) >= 3
    assert len({id(session) for session in session_factory.sessions}) == len(
        session_factory.sessions
    )


@pytest.mark.asyncio
async def test_worker_cancels_execution_when_heartbeat_fails():
    store = FailingHeartbeatStore()
    execution = _execution()
    queued = await store.enqueue(execution)
    orchestrator = DelayedOrchestrator(delay_seconds=1)
    worker = _worker(
        store=store,
        orchestrator=orchestrator,
        session_factory=TrackingSessionFactory(),
    )

    with pytest.raises(RuntimeError, match="heartbeat persistence failed"):
        await worker.run_once()

    assert orchestrator.cancelled.is_set()
    persisted = await store.get(queued.flow_id)
    assert persisted is not None
    assert persisted.status == AgentFlowStatus.RUNNING
    assert persisted.pending_execution_payload is not None
