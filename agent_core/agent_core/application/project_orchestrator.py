from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.agent_platform.agents.base import AgentNextAction, AgentResult, AgentRunStatus
from agent_core.agent_platform.agents.planning import PlanningAgentRequest
from agent_core.agent_platform.config import load_agent_platform_config
from agent_core.agent_platform.orchestration import AgentExecutionRequest, AgentOrchestrationResult
from agent_core.application.openproject_approvals import (
    OpenProjectApprovalDecision,
    classify_openproject_approval,
)
from agent_core.application.openproject_feedback import (
    OpenProjectFeedbackClassification,
    OpenProjectFeedbackIntent,
    classify_openproject_feedback,
)
from agent_core.domain.enums import (
    AgentExecutionStatus,
    ApprovalScope,
    PlanningSessionStatus,
    PlanVersionStatus,
)
from agent_core.domain.events import EventEnvelope
from agent_core.models import ExternalArtifact, PlanningSession, PlanVersion, Project
from agent_core.persistence.approvals import SqlAlchemyApprovalRecordStore
from agent_core.ports.approvals import (
    ApprovalRecordInput,
    ApprovalRecordStorePort,
)
from agent_core.ports.event_inbox import EventInboxPort
from agent_core.ports.executions import AgentExecutionRecorderPort


class OrchestrationAction(StrEnum):
    IGNORED = "ignored"
    UNMAPPED_PROJECT = "unmapped_project"
    CONTEXT_SYNC_ONLY = "context_sync_only"
    NO_WAITING_SESSION = "no_waiting_session"
    RESUME_PLANNING = "resume_planning"


@dataclass(frozen=True)
class OrchestrationResult:
    event_id: str
    action: OrchestrationAction
    reason: str
    project_id: UUID | None = None
    planning_session_id: UUID | None = None
    thread_id: str | None = None
    execution_id: UUID | None = None
    workflow_result: dict[str, Any] | None = None
    approval_id: UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action.value,
            "reason": self.reason,
            "project_id": str(self.project_id) if self.project_id else None,
            "planning_session_id": (
                str(self.planning_session_id) if self.planning_session_id else None
            ),
            "thread_id": self.thread_id,
            "execution_id": str(self.execution_id) if self.execution_id else None,
            "approval_id": str(self.approval_id) if self.approval_id else None,
            "workflow_result": self.workflow_result,
        }


@dataclass(frozen=True)
class ResolvedOpenProjectMapping:
    project_id: UUID
    artifact_id: UUID | None = None


class PlanningRunnerPort(Protocol):
    async def run(self, session_id: UUID) -> dict[str, Any]:
        ...


class AgentPlatformServicePort(Protocol):
    async def execute(self, request: AgentExecutionRequest) -> AgentOrchestrationResult:
        ...


class ProjectEventOrchestrator:
    def __init__(
        self,
        *,
        db: AsyncSession,
        event_inbox: EventInboxPort,
        planning_runner: PlanningRunnerPort | None = None,
        agent_platform_service: AgentPlatformServicePort | None = None,
        execution_recorder: AgentExecutionRecorderPort | None = None,
        approval_store: ApprovalRecordStorePort | None = None,
    ) -> None:
        self.db = db
        self.event_inbox = event_inbox
        self.planning_runner = planning_runner
        self.agent_platform_service = agent_platform_service
        self.execution_recorder = execution_recorder
        self.approval_store = approval_store

    async def handle_persisted_event(self, event_id: str) -> OrchestrationResult:
        envelope = await self.event_inbox.get(event_id)
        if envelope is None:
            raise KeyError(f"Webhook event not found: {event_id}")

        await self.event_inbox.mark_processing(event_id)
        try:
            result = await self.route_event(event_id=event_id, envelope=envelope)
        except Exception as exc:
            await self.event_inbox.mark_failed(event_id, str(exc))
            raise

        await self.event_inbox.mark_processed(event_id)
        return result

    async def route_event(
        self,
        *,
        event_id: str,
        envelope: EventEnvelope,
    ) -> OrchestrationResult:
        if envelope.source != "openproject":
            return OrchestrationResult(
                event_id=event_id,
                action=OrchestrationAction.IGNORED,
                reason=f"Unsupported event source: {envelope.source}",
            )

        mapping = await self._resolve_openproject_mapping(envelope)
        if mapping is None:
            return OrchestrationResult(
                event_id=event_id,
                action=OrchestrationAction.UNMAPPED_PROJECT,
                reason="No local project mapping exists for this OpenProject event",
            )
        project_id = mapping.project_id

        feedback = classify_openproject_feedback(envelope)
        approval_decision = classify_openproject_approval(envelope, feedback)
        if not feedback.resumable and approval_decision is None:
            return OrchestrationResult(
                event_id=event_id,
                action=OrchestrationAction.CONTEXT_SYNC_ONLY,
                reason="Event does not currently map to a resumable planning action",
                project_id=project_id,
            )

        plan_version = None
        if (
            approval_decision is not None
            and approval_decision.approval_scope == ApprovalScope.PLANNING
        ):
            plan_version = await self._find_latest_review_plan_version(project_id)

        session = None
        if (
            approval_decision is None
            or approval_decision.approval_scope == ApprovalScope.PLANNING
        ):
            session = await self._find_planning_session_for_feedback(
                project_id=project_id,
                feedback=feedback,
                approval_decision=approval_decision,
            )

        approval_id = None
        if approval_decision is not None:
            approval = await self._record_approval(
                event_id=event_id,
                envelope=envelope,
                project_id=project_id,
                artifact_id=mapping.artifact_id,
                approval_decision=approval_decision,
                planning_session_id=session.id if session else None,
                plan_version_id=plan_version.id if plan_version else None,
            )
            approval_id = approval.approval_id

        if (
            approval_decision is not None
            and approval_decision.approval_scope == ApprovalScope.TASK_COMPLETION
        ):
            return OrchestrationResult(
                event_id=event_id,
                action=OrchestrationAction.CONTEXT_SYNC_ONLY,
                reason=(
                    "Task-completion approval recorded; coding and verification "
                    "workflow resume is not enabled in this slice"
                ),
                project_id=project_id,
                approval_id=approval_id,
            )

        if session is None:
            return OrchestrationResult(
                event_id=event_id,
                action=OrchestrationAction.NO_WAITING_SESSION,
                reason="No waiting planning session exists for the mapped project",
                project_id=project_id,
                approval_id=approval_id,
            )

        thread_id = f"planning-session-{session.id}"
        execution = None
        if self.execution_recorder is not None:
            execution = await self.execution_recorder.start(
                project_id=project_id,
                agent_name="planning",
                thread_id=thread_id,
                trigger_event_id=event_id,
                config_snapshot={
                    "workflow": "planning",
                    "event_source": envelope.source,
                    "event_type": envelope.event_type,
                    "feedback_intent": feedback.intent.value,
                    "approval_scope": (
                        approval_decision.approval_scope.value
                        if approval_decision
                        else None
                    ),
                },
        )

        try:
            workflow_result, agent_result = await self._resume_planning(
                event_id=event_id,
                envelope=envelope,
                session=session,
                project_id=project_id,
                feedback=feedback,
                approval_decision=approval_decision,
                execution_id=execution.execution_id if execution else None,
            )
        except Exception as exc:
            if execution is not None:
                await self.execution_recorder.finish(
                    execution.execution_id,
                    status=AgentExecutionStatus.FAILED,
                    error_summary={
                        "type": exc.__class__.__name__,
                        "message": str(exc)[:2000],
                    },
                )
            raise

        if execution is not None:
            await self.execution_recorder.finish(
                execution.execution_id,
                status=(
                    classify_agent_result_completion(agent_result)
                    if agent_result is not None
                    else classify_workflow_completion(workflow_result)
                ),
            )

        return OrchestrationResult(
            event_id=event_id,
            action=OrchestrationAction.RESUME_PLANNING,
            reason=(
                "Resumed the waiting planning agent through the platform"
                if agent_result is not None
                else "Resumed the waiting planning workflow for the mapped project"
            ),
            project_id=project_id,
            planning_session_id=session.id,
            thread_id=thread_id,
            execution_id=(
                agent_result.execution_id
                if agent_result is not None
                else execution.execution_id
                if execution
                else None
            ),
            workflow_result=workflow_result,
            approval_id=approval_id,
        )

    async def _resume_planning(
        self,
        *,
        event_id: str,
        envelope: EventEnvelope,
        session: PlanningSession,
        project_id: UUID,
        feedback: OpenProjectFeedbackClassification,
        approval_decision: OpenProjectApprovalDecision | None,
        execution_id: UUID | None,
    ) -> tuple[dict[str, Any], AgentResult | None]:
        if self.agent_platform_service is not None:
            project_key = await self._project_key(project_id)
            request = PlanningAgentRequest(
                execution_id=execution_id or uuid4(),
                project_id=project_key,
                objective=session.original_request or "Resume planning from OpenProject feedback.",
                original_request=session.original_request,
                session_id=session.id,
                metadata={
                    "source_event_id": event_id,
                    "event_source": envelope.source,
                    "event_type": envelope.event_type,
                    "feedback_intent": feedback.intent.value,
                    "approval_scope": (
                        approval_decision.approval_scope.value
                        if approval_decision
                        else None
                    ),
                },
            )
            platform_result = await self.agent_platform_service.execute(
                AgentExecutionRequest(
                    workflow_id=f"planning-session-{session.id}",
                    agent_type="planning",
                    request=request,
                    config=load_agent_platform_config().agents["planning"],
                    correlation_id=event_id,
                )
            )
            return _platform_workflow_result(platform_result), platform_result.result

        if self.planning_runner is None:
            raise RuntimeError("No planning runner or agent platform service is configured")

        return await self.planning_runner.run(session.id), None

    async def _resolve_openproject_mapping(
        self,
        envelope: EventEnvelope,
    ) -> ResolvedOpenProjectMapping | None:
        project_artifact = await self._find_openproject_artifact(
            artifact_type="project",
            external_id=envelope.external_project_id,
        )
        if project_artifact is not None:
            return ResolvedOpenProjectMapping(
                project_id=project_artifact.project_id,
                artifact_id=getattr(project_artifact, "id", None),
            )

        work_package_artifact = await self._find_openproject_artifact(
            artifact_type="work_package",
            external_id=envelope.external_work_package_id,
        )
        if work_package_artifact is not None:
            return ResolvedOpenProjectMapping(
                project_id=work_package_artifact.project_id,
                artifact_id=getattr(work_package_artifact, "id", None),
            )

        return None

    async def _find_openproject_artifact(
        self,
        *,
        artifact_type: str,
        external_id: str | None,
    ) -> ExternalArtifact | None:
        if not external_id:
            return None

        return await self.db.scalar(
            select(ExternalArtifact).where(
                ExternalArtifact.system_name == "openproject",
                ExternalArtifact.artifact_type == artifact_type,
                ExternalArtifact.external_id == external_id,
            )
        )

    async def _find_planning_session_for_feedback(
        self,
        *,
        project_id: UUID,
        feedback: OpenProjectFeedbackClassification,
        approval_decision: OpenProjectApprovalDecision | None = None,
    ) -> PlanningSession | None:
        waiting_statuses = _planning_session_statuses_for_feedback(
            feedback=feedback,
            approval_decision=approval_decision,
        )
        return await self.db.scalar(
            select(PlanningSession)
            .where(
                PlanningSession.project_id == project_id,
                PlanningSession.status.in_([status.value for status in waiting_statuses]),
            )
            .order_by(PlanningSession.created_at.desc())
            .limit(1)
        )

    async def _find_latest_review_plan_version(
        self,
        project_id: UUID,
    ) -> PlanVersion | None:
        return await self.db.scalar(
            select(PlanVersion)
            .where(
                PlanVersion.project_id == project_id,
                PlanVersion.status.in_(
                    [
                        PlanVersionStatus.AWAITING_REVIEW.value,
                        PlanVersionStatus.DRAFT.value,
                    ]
                ),
            )
            .order_by(PlanVersion.version_number.desc())
            .limit(1)
        )

    async def _project_key(self, project_id: UUID) -> str:
        project = await self.db.scalar(select(Project).where(Project.id == project_id))
        if project is None:
            raise KeyError(f"Project not found: {project_id}")
        return project.project_key

    async def _record_approval(
        self,
        *,
        event_id: str,
        envelope: EventEnvelope,
        project_id: UUID,
        artifact_id: UUID | None,
        approval_decision: OpenProjectApprovalDecision,
        planning_session_id: UUID | None,
        plan_version_id: UUID | None,
    ):
        store = self.approval_store or SqlAlchemyApprovalRecordStore(self.db)
        return await store.record(
            ApprovalRecordInput(
                project_id=project_id,
                approval_scope=approval_decision.approval_scope,
                decision=approval_decision.decision,
                source_system=envelope.source,
                source_event_id=event_id,
                planning_session_id=planning_session_id,
                plan_version_id=plan_version_id,
                external_artifact_id=artifact_id,
                external_project_id=envelope.external_project_id,
                external_work_package_id=envelope.external_work_package_id,
                external_comment_id=envelope.external_comment_id,
                reason=approval_decision.reason,
                payload=envelope.payload,
            )
        )


def should_resume_planning(envelope: EventEnvelope) -> bool:
    feedback = classify_openproject_feedback(envelope)
    approval_decision = classify_openproject_approval(envelope, feedback)
    if (
        approval_decision is not None
        and approval_decision.approval_scope == ApprovalScope.TASK_COMPLETION
    ):
        return False
    return feedback.resumable


def _planning_session_statuses_for_feedback(
    *,
    feedback: OpenProjectFeedbackClassification,
    approval_decision: OpenProjectApprovalDecision | None,
) -> tuple[PlanningSessionStatus, ...]:
    review_feedback_intents = {
        OpenProjectFeedbackIntent.APPROVAL,
        OpenProjectFeedbackIntent.CANCELLATION,
        OpenProjectFeedbackIntent.PLAN_FEEDBACK,
        OpenProjectFeedbackIntent.REQUIREMENT_CHANGE,
        OpenProjectFeedbackIntent.REWORK_REQUEST,
    }
    if (
        approval_decision is not None
        and approval_decision.approval_scope == ApprovalScope.PLANNING
    ) or feedback.intent in review_feedback_intents:
        return (
            PlanningSessionStatus.PLAN_DRAFTED,
            PlanningSessionStatus.AWAITING_REVIEW,
            PlanningSessionStatus.READY_FOR_PLANNING,
            PlanningSessionStatus.NEEDS_CLARIFICATION,
            PlanningSessionStatus.INTAKE,
        )

    return (
        PlanningSessionStatus.INTAKE,
        PlanningSessionStatus.NEEDS_CLARIFICATION,
        PlanningSessionStatus.READY_FOR_PLANNING,
    )


def classify_workflow_completion(workflow_result: dict[str, Any]) -> AgentExecutionStatus:
    if workflow_result.get("clarification_questions"):
        return AgentExecutionStatus.WAITING

    if workflow_result.get("ambiguity_status") == "needs_clarification":
        return AgentExecutionStatus.WAITING

    return AgentExecutionStatus.SUCCEEDED


def classify_agent_result_completion(result: AgentResult) -> AgentExecutionStatus:
    if result.next_action in {
        AgentNextAction.REQUEST_APPROVAL,
        AgentNextAction.REQUEST_CLARIFICATION,
    }:
        return AgentExecutionStatus.WAITING

    if result.status in {AgentRunStatus.WAITING, AgentRunStatus.BLOCKED}:
        return AgentExecutionStatus.WAITING

    if result.status == AgentRunStatus.SUCCEEDED:
        return AgentExecutionStatus.SUCCEEDED

    return AgentExecutionStatus.FAILED


def _platform_workflow_result(result: AgentOrchestrationResult) -> dict[str, Any]:
    agent_payload = result.result.model_dump(mode="json")
    return {
        "platform": True,
        "persisted_result_id": str(result.persisted.result_id),
        "agent_result": agent_payload,
        "route": result.route.model_dump(mode="json"),
        "ambiguity_status": (
            "needs_clarification"
            if result.result.next_action == AgentNextAction.REQUEST_CLARIFICATION
            else result.result.status.value
        ),
        "clarification_questions": agent_payload.get("clarification_questions", []),
    }
