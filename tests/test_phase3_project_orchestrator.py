from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentResult,
    AgentRunStatus,
)
from agent_core.agent_platform.orchestration import (
    AgentOrchestrationResult,
    AgentRouteDecision,
    PersistedAgentResult,
)
from agent_core.application.project_orchestrator import (
    classify_agent_result_completion,
    classify_workflow_completion,
    OrchestrationAction,
    ProjectEventOrchestrator,
    should_resume_planning,
)
from agent_core.domain.enums import (
    AgentExecutionStatus,
    ApprovalDecision,
    ApprovalScope,
)
from agent_core.domain.events import EventEnvelope
from agent_core.ports.executions import AgentExecutionStart


@dataclass
class FakeInbox:
    event: EventEnvelope | None
    marks: list[tuple[str, str]]

    async def get(self, event_id: str) -> EventEnvelope | None:
        self.marks.append(("get", event_id))
        return self.event

    async def mark_processing(self, event_id: str) -> None:
        self.marks.append(("processing", event_id))

    async def mark_processed(self, event_id: str) -> None:
        self.marks.append(("processed", event_id))

    async def mark_failed(self, event_id: str, message: str) -> None:
        self.marks.append(("failed", event_id))


class FakeDb:
    def __init__(self, *scalar_results: Any):
        self.scalar_results = list(scalar_results)
        self.statements: list[Any] = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.scalar_results.pop(0)


class FakeRunner:
    def __init__(self, result: dict[str, Any] | None = None, error: Exception | None = None):
        self.result = result or {"selected_skill": "planning_decomposition"}
        self.error = error
        self.calls: list[Any] = []

    async def run(self, session_id):
        self.calls.append(session_id)
        if self.error:
            raise self.error
        return self.result


class FakeAgentPlatformService:
    def __init__(
        self,
        *,
        status: AgentRunStatus = AgentRunStatus.WAITING,
        next_action: AgentNextAction = AgentNextAction.REQUEST_CLARIFICATION,
    ):
        self.status = status
        self.next_action = next_action
        self.calls: list[Any] = []

    async def execute(self, request):
        self.calls.append(request)
        result = AgentResult(
            execution_id=request.request.execution_id,
            project_id=request.request.project_id,
            task_id=request.request.task_id,
            agent_type=request.agent_type,
            status=self.status,
            summary="Platform planning resumed.",
            next_action=self.next_action,
        )
        return AgentOrchestrationResult(
            result=result,
            persisted=PersistedAgentResult(result=result),
            route=AgentRouteDecision(
                next_agent_type=None,
                requires_approval=False,
                escalate=self.next_action == AgentNextAction.REQUEST_CLARIFICATION,
                reason="Platform route.",
            ),
        )


class FakeExecutionRecorder:
    def __init__(self):
        self.execution_id = uuid4()
        self.start_calls: list[dict[str, Any]] = []
        self.finish_calls: list[dict[str, Any]] = []

    async def start(self, **kwargs):
        self.start_calls.append(kwargs)
        return AgentExecutionStart(
            execution_id=self.execution_id,
            attempt_number=1,
        )

    async def finish(self, execution_id, **kwargs):
        self.finish_calls.append({"execution_id": execution_id, **kwargs})


class FakeApprovalStore:
    def __init__(self):
        self.approval_id = uuid4()
        self.records: list[Any] = []

    async def record(self, approval):
        self.records.append(approval)
        return SimpleNamespace(
            approval_id=self.approval_id,
            project_id=approval.project_id,
            approval_scope=approval.approval_scope,
            decision=approval.decision,
        )


@pytest.mark.asyncio
async def test_project_orchestrator_resumes_waiting_planning_thread_from_event():
    project_id = uuid4()
    session_id = uuid4()
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_project_id="12",
        external_comment_id="99",
        payload={"action": "work_package.comment_created"},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(
        SimpleNamespace(project_id=project_id),
        SimpleNamespace(id=session_id),
    )
    runner = FakeRunner()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
    )

    result = await orchestrator.handle_persisted_event("event-1")

    assert result.action == OrchestrationAction.RESUME_PLANNING
    assert result.project_id == project_id
    assert result.planning_session_id == session_id
    assert result.thread_id == f"planning-session-{session_id}"
    assert runner.calls == [session_id]
    assert inbox.marks == [
        ("get", "event-1"),
        ("processing", "event-1"),
        ("processed", "event-1"),
    ]


@pytest.mark.asyncio
async def test_project_orchestrator_resumes_planning_through_agent_platform():
    project_id = uuid4()
    session_id = uuid4()
    event_id = str(uuid4())
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_project_id="12",
        external_comment_id="99",
        payload={"action": "work_package.comment_created"},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(
        SimpleNamespace(id=uuid4(), project_id=project_id),
        SimpleNamespace(
            id=session_id,
            project_id=project_id,
            original_request="Build the modular platform.",
        ),
        SimpleNamespace(id=project_id, project_key="demo-platform"),
    )
    platform = FakeAgentPlatformService()
    recorder = FakeExecutionRecorder()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        agent_platform_service=platform,
        execution_recorder=recorder,
    )

    result = await orchestrator.handle_persisted_event(event_id)

    assert result.action == OrchestrationAction.RESUME_PLANNING
    assert result.reason == "Resumed the waiting planning agent through the platform"
    assert result.project_id == project_id
    assert result.planning_session_id == session_id
    assert result.execution_id == recorder.execution_id
    assert result.workflow_result is not None
    assert result.workflow_result["platform"] is True
    assert result.workflow_result["agent_result"]["project_id"] == "demo-platform"
    assert result.workflow_result["ambiguity_status"] == "needs_clarification"

    request = platform.calls[0]
    assert request.agent_type == "planning"
    assert request.workflow_id == f"planning-session-{session_id}"
    assert request.correlation_id == event_id
    assert request.request.execution_id == recorder.execution_id
    assert request.request.project_id == "demo-platform"
    assert request.request.session_id == session_id
    assert request.request.metadata["source_event_id"] == event_id

    assert recorder.finish_calls == [
        {
            "execution_id": recorder.execution_id,
            "status": AgentExecutionStatus.WAITING,
        }
    ]


@pytest.mark.asyncio
async def test_project_orchestrator_records_planning_execution_for_resume():
    project_id = uuid4()
    session_id = uuid4()
    event_id = str(uuid4())
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_project_id="12",
        external_comment_id="99",
        payload={"action": "work_package.comment_created"},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(
        SimpleNamespace(project_id=project_id),
        SimpleNamespace(id=session_id),
    )
    runner = FakeRunner(result={"ambiguity_status": "clear"})
    recorder = FakeExecutionRecorder()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
        execution_recorder=recorder,
    )

    result = await orchestrator.handle_persisted_event(event_id)

    assert result.execution_id == recorder.execution_id
    assert recorder.start_calls == [
        {
            "project_id": project_id,
            "agent_name": "planning",
            "thread_id": f"planning-session-{session_id}",
            "trigger_event_id": event_id,
            "config_snapshot": {
                "workflow": "planning",
                "event_source": "openproject",
                "event_type": "work_package.comment_created",
                "feedback_intent": "general_comment",
                "approval_scope": None,
            },
        }
    ]
    assert recorder.finish_calls == [
        {
            "execution_id": recorder.execution_id,
            "status": AgentExecutionStatus.SUCCEEDED,
        }
    ]


@pytest.mark.asyncio
async def test_project_orchestrator_records_plan_approval_and_resumes_review_session():
    project_id = uuid4()
    artifact_id = uuid4()
    plan_version_id = uuid4()
    session_id = uuid4()
    event_id = str(uuid4())
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_project_id="12",
        external_work_package_id="34",
        external_comment_id="99",
        payload={"comment": {"raw": "Please approve this plan."}},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(
        SimpleNamespace(id=artifact_id, project_id=project_id),
        SimpleNamespace(id=plan_version_id),
        SimpleNamespace(id=session_id),
    )
    runner = FakeRunner(result={"ambiguity_status": "clear"})
    approval_store = FakeApprovalStore()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
        approval_store=approval_store,
    )

    result = await orchestrator.handle_persisted_event(event_id)

    assert result.action == OrchestrationAction.RESUME_PLANNING
    assert result.approval_id == approval_store.approval_id
    assert runner.calls == [session_id]
    approval = approval_store.records[0]
    assert approval.project_id == project_id
    assert approval.planning_session_id == session_id
    assert approval.plan_version_id == plan_version_id
    assert approval.external_artifact_id == artifact_id
    assert approval.approval_scope == ApprovalScope.PLANNING
    assert approval.decision == ApprovalDecision.APPROVED
    assert approval.source_event_id == event_id
    assert approval.external_project_id == "12"
    assert approval.external_work_package_id == "34"
    assert approval.external_comment_id == "99"


@pytest.mark.asyncio
async def test_project_orchestrator_records_task_completion_approval_without_planning_resume():
    project_id = uuid4()
    artifact_id = uuid4()
    event_id = str(uuid4())
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_work_package_id="34",
        external_comment_id="99",
        payload={"comment": {"raw": "Approved task completion."}},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(SimpleNamespace(id=artifact_id, project_id=project_id))
    runner = FakeRunner()
    approval_store = FakeApprovalStore()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
        approval_store=approval_store,
    )

    result = await orchestrator.handle_persisted_event(event_id)

    assert result.action == OrchestrationAction.CONTEXT_SYNC_ONLY
    assert result.project_id == project_id
    assert result.approval_id == approval_store.approval_id
    assert runner.calls == []
    approval = approval_store.records[0]
    assert approval.approval_scope == ApprovalScope.TASK_COMPLETION
    assert approval.decision == ApprovalDecision.APPROVED
    assert approval.external_artifact_id == artifact_id


@pytest.mark.asyncio
async def test_project_orchestrator_returns_unmapped_without_runner_call():
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_project_id="12",
        payload={"action": "work_package.comment_created"},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(None, None)
    runner = FakeRunner()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
    )

    result = await orchestrator.handle_persisted_event("event-1")

    assert result.action == OrchestrationAction.UNMAPPED_PROJECT
    assert runner.calls == []
    assert inbox.marks[-1] == ("processed", "event-1")


@pytest.mark.asyncio
async def test_project_orchestrator_routes_non_resumable_events_to_context_sync_only():
    project_id = uuid4()
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        payload={"action": "work_package.updated"},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(SimpleNamespace(project_id=project_id))
    runner = FakeRunner()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
    )

    result = await orchestrator.handle_persisted_event("event-1")

    assert result.action == OrchestrationAction.CONTEXT_SYNC_ONLY
    assert result.project_id == project_id
    assert runner.calls == []
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_project_orchestrator_marks_failed_when_resume_raises():
    project_id = uuid4()
    session_id = uuid4()
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_project_id="12",
        external_comment_id="99",
        payload={"action": "work_package.comment_created"},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(
        SimpleNamespace(project_id=project_id),
        SimpleNamespace(id=session_id),
    )
    runner = FakeRunner(error=TimeoutError("timed out"))
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
    )

    with pytest.raises(TimeoutError):
        await orchestrator.handle_persisted_event("event-1")

    assert ("failed", "event-1") in inbox.marks
    assert ("processed", "event-1") not in inbox.marks


@pytest.mark.asyncio
async def test_project_orchestrator_marks_execution_failed_when_resume_raises():
    project_id = uuid4()
    session_id = uuid4()
    event_id = str(uuid4())
    event = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_project_id="12",
        external_comment_id="99",
        payload={"action": "work_package.comment_created"},
    )
    inbox = FakeInbox(event=event, marks=[])
    db = FakeDb(
        SimpleNamespace(project_id=project_id),
        SimpleNamespace(id=session_id),
    )
    runner = FakeRunner(error=TimeoutError("timed out"))
    recorder = FakeExecutionRecorder()
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=inbox,
        planning_runner=runner,
        execution_recorder=recorder,
    )

    with pytest.raises(TimeoutError):
        await orchestrator.handle_persisted_event(event_id)

    assert recorder.finish_calls == [
        {
            "execution_id": recorder.execution_id,
            "status": AgentExecutionStatus.FAILED,
            "error_summary": {
                "type": "TimeoutError",
                "message": "timed out",
            },
        }
    ]


def test_should_resume_planning_uses_comment_and_feedback_markers():
    assert should_resume_planning(
        EventEnvelope(
            source="openproject",
            event_type="work_package.updated",
            external_comment_id="99",
            payload={},
        )
    )
    assert should_resume_planning(
        EventEnvelope(
            source="openproject",
            event_type="work_package.updated",
            payload={"action": "approval.created"},
        )
    )
    assert not should_resume_planning(
        EventEnvelope(
            source="openproject",
            event_type="work_package.comment_created",
            external_work_package_id="34",
            external_comment_id="99",
            payload={"comment": {"raw": "Approved task completion."}},
        )
    )
    assert not should_resume_planning(
        EventEnvelope(
            source="openproject",
            event_type="work_package.updated",
            payload={"action": "work_package.updated"},
        )
    )


def test_classify_workflow_completion_marks_waiting_for_clarification():
    assert classify_workflow_completion({"ambiguity_status": "clear"}) == (
        AgentExecutionStatus.SUCCEEDED
    )
    assert classify_workflow_completion({"ambiguity_status": "needs_clarification"}) == (
        AgentExecutionStatus.WAITING
    )
    assert classify_workflow_completion({"clarification_questions": [{"question": "Why?"}]}) == (
        AgentExecutionStatus.WAITING
    )


def test_classify_agent_result_completion_maps_platform_statuses():
    assert classify_agent_result_completion(
        AgentResult(
            execution_id=uuid4(),
            agent_type="planning",
            status=AgentRunStatus.SUCCEEDED,
            summary="Done.",
            next_action=AgentNextAction.RUN_CODING,
        )
    ) == AgentExecutionStatus.SUCCEEDED
    assert classify_agent_result_completion(
        AgentResult(
            execution_id=uuid4(),
            agent_type="planning",
            status=AgentRunStatus.SUCCEEDED,
            summary="Waiting.",
            next_action=AgentNextAction.REQUEST_APPROVAL,
        )
    ) == AgentExecutionStatus.WAITING
    assert classify_agent_result_completion(
        AgentResult(
            execution_id=uuid4(),
            agent_type="planning",
            status=AgentRunStatus.FAILED,
            summary="Failed.",
        )
    ) == AgentExecutionStatus.FAILED
