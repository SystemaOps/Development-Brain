from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from agent_core.agent_platform.agents.base.errors import AgentValidationError
from agent_core.agent_platform.agents.verification.config import (
    VerificationAgentConfig,
)
from agent_core.agent_platform.agents.verification.override import (
    VerificationOverrideCommand,
    VerificationOverridePolicyError,
    VerificationOverrideType,
    assess_verification_override,
)
from agent_core.agent_platform.agents.verification.state import (
    VerificationAgentResult,
)
from agent_core.agent_platform.config.models import (
    AgentConfig,
    materialize_agent_config,
)
from agent_core.agent_platform.factory import AgentFactory, create_default_agent_factory
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowApproval,
    AgentFlowNotFoundError,
    AgentFlowOrchestrator,
    AgentFlowOverrideRecord,
    AgentFlowResult,
    AgentFlowStore,
    AgentFlowVersionConflictError,
    AgentOrchestrationResult,
    AgentOrchestrator,
    AgentTransitionRequestResolver,
    PersistedAgentFlow,
)
from agent_core.agent_platform.orchestration.flow import AgentFlowStatus
from agent_core.agent_platform.runtime import AgentDependencyContainer
from agent_core.domain.enums import ApprovalDecision
from agent_core.services.verification_projection_service import (
    VerificationOpenProjectProjectionService,
)


class AgentPlatformService:
    """Application-facing entry point for running registered agents through the orchestrator."""

    def __init__(
        self,
        *,
        dependencies: AgentDependencyContainer,
        factory: AgentFactory | None = None,
        orchestrator: AgentOrchestrator | None = None,
        transition_resolver: AgentTransitionRequestResolver | None = None,
        flow_store: AgentFlowStore | None = None,
        verification_projection_service: VerificationOpenProjectProjectionService
        | None = None,
        flow_lease_seconds: int = 300,
        flow_recovery_enabled: bool = True,
    ) -> None:
        self.dependencies = dependencies
        self.factory = factory or create_default_agent_factory(dependencies)
        self.orchestrator = orchestrator or AgentOrchestrator(
            factory=self.factory,
            dependencies=dependencies,
        )
        self.transition_resolver = transition_resolver
        self.flow_store = flow_store
        self.verification_projection_service = (
            verification_projection_service
            or VerificationOpenProjectProjectionService(
                dependencies.work_package_gateway
            )
        )
        self.flow_lease_seconds = flow_lease_seconds
        self.flow_recovery_enabled = flow_recovery_enabled

    async def execute(self, request: AgentExecutionRequest) -> AgentOrchestrationResult:
        outcome = await self.orchestrator.run_once(request)
        await self.verification_projection_service.project_execution(request, outcome)
        return outcome

    async def enqueue_flow(
        self,
        request: AgentExecutionRequest,
        *,
        max_steps: int = 10,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        return await self.flow_store.enqueue(request, max_steps=max_steps)

    async def execute_flow(
        self,
        request: AgentExecutionRequest,
        *,
        transition_resolver: AgentTransitionRequestResolver | None = None,
        max_steps: int = 10,
    ) -> AgentFlowResult:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        reservation = (
            await self.flow_store.reserve(
                request,
                lease_owner=_lease_owner("start", request),
                lease_seconds=self.flow_lease_seconds,
            )
            if self.flow_store is not None
            else None
        )
        flow_orchestrator = AgentFlowOrchestrator(
            step_orchestrator=self.orchestrator,
            transition_resolver=(
                transition_resolver if transition_resolver is not None else self.transition_resolver
            ),
        )
        result = await flow_orchestrator.run(request, max_steps=max_steps)
        await self.verification_projection_service.project_flow(result)
        if reservation is None:
            return result
        persisted = await self.flow_store.complete_run(
            flow_id=reservation.flow_id,
            result=result,
            expected_version=reservation.version,
            lease_id=_active_lease_id(reservation),
        )
        return result.model_copy(
            update={
                "flow_id": persisted.flow_id,
                "version": persisted.version,
            }
        )

    async def start_flow(
        self,
        request: AgentExecutionRequest,
        *,
        transition_resolver: AgentTransitionRequestResolver | None = None,
        max_steps: int = 10,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        result = await self.execute_flow(
            request,
            transition_resolver=transition_resolver,
            max_steps=max_steps,
        )
        if result.flow_id is None:
            raise RuntimeError("Durable flow execution did not return a flow_id")
        snapshot = await self.flow_store.get(result.flow_id)
        if snapshot is None:
            raise AgentFlowNotFoundError(f"Agent flow not found after execution: {result.flow_id}")
        return snapshot

    async def get_flow(self, flow_id: UUID) -> PersistedAgentFlow:
        self._require_flow_store()
        snapshot = await self.flow_store.get(flow_id)
        if snapshot is None:
            raise AgentFlowNotFoundError(f"Agent flow not found: {flow_id}")
        return snapshot

    async def get_flow_by_workflow(
        self,
        *,
        project_id: str,
        workflow_id: str,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        snapshot = await self.flow_store.get_by_workflow(
            project_id=project_id,
            workflow_id=workflow_id,
        )
        if snapshot is None:
            raise AgentFlowNotFoundError(f"Agent flow not found for workflow: {workflow_id}")
        return snapshot

    async def override_verification_flow(
        self,
        *,
        flow_id: UUID,
        expected_version: int,
        command: VerificationOverrideCommand,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        current = await self.get_flow(flow_id)
        if current.version != expected_version:
            raise AgentFlowVersionConflictError(
                f"Agent flow version conflict: expected {expected_version}, found {current.version}"
            )
        if current.status != AgentFlowStatus.WAITING_FOR_APPROVAL:
            raise AgentValidationError("Verification override requires a flow waiting for approval")
        if not current.steps:
            raise AgentValidationError(
                "Verification override requires a persisted Verification Agent step"
            )

        source = current.steps[-1]
        if source.agent_type != "verification":
            raise AgentValidationError(
                "Verification override can only target the latest Verification Agent step"
            )
        try:
            result = VerificationAgentResult.model_validate(source.result_payload)
            generic_config = AgentConfig.model_validate(source.request_payload.get("config"))
            config = VerificationAgentConfig.model_validate(
                materialize_agent_config(generic_config)
            )
            assessment = assess_verification_override(
                config=config,
                result=result,
            )
        except (ValidationError, VerificationOverridePolicyError) as exc:
            raise AgentValidationError(str(exc)) from exc

        override = AgentFlowOverrideRecord(
            override_id=_verification_override_id(
                flow_id=flow_id,
                source_result_id=source.result_id,
                override_reference=command.override_reference,
            ),
            override_type=VerificationOverrideType.COMPLETION.value,
            source_step_sequence=source.sequence,
            source_agent_type=source.agent_type,
            source_execution_id=source.execution_id,
            source_result_id=source.result_id,
            original_status=result.status,
            original_next_action=result.next_action,
            original_outcome=assessment.original_verdict,
            finding_codes=assessment.finding_codes,
            affected_item_keys=assessment.acceptance_criterion_keys,
            actor=command.actor,
            reason=command.reason,
            override_reference=command.override_reference,
            metadata=command.metadata,
        )
        await self.verification_projection_service.project_override(
            flow=current,
            source=source,
            result=result,
            override=override,
        )
        return await self.flow_store.complete_override(
            flow_id=flow_id,
            expected_version=expected_version,
            override=override,
        )

    async def resume_flow(
        self,
        *,
        flow_id: UUID,
        expected_version: int,
        request: AgentExecutionRequest | None = None,
        approval: AgentFlowApproval | None = None,
        transition_resolver: AgentTransitionRequestResolver | None = None,
        max_steps: int = 10,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        current = await self.get_flow(flow_id)
        _validate_resume_status(current)

        if current.status == AgentFlowStatus.WAITING_FOR_APPROVAL:
            if approval is None:
                raise AgentValidationError("Approval evidence is required to resume this flow")
            if approval.decision != ApprovalDecision.APPROVED:
                status = (
                    AgentFlowStatus.CHANGES_REQUESTED
                    if approval.decision == ApprovalDecision.CHANGES_REQUESTED
                    else AgentFlowStatus.CANCELLED
                )
                return await self.flow_store.close(
                    flow_id=flow_id,
                    status=status,
                    reason=approval.reason or f"Flow {status.value}.",
                    expected_version=expected_version,
                    approval=approval,
                )
        elif approval is not None:
            raise AgentValidationError(
                "Approval evidence is only valid for a flow waiting for approval"
            )

        if request is None:
            raise AgentValidationError("A typed execution request is required to resume this flow")
        _validate_resume_request(current, request)
        reservation = await self.flow_store.begin_resume(
            flow_id=flow_id,
            execution=request,
            expected_version=expected_version,
            approval=approval,
            lease_owner=_lease_owner("resume", request),
            lease_seconds=self.flow_lease_seconds,
        )
        flow_orchestrator = AgentFlowOrchestrator(
            step_orchestrator=self.orchestrator,
            transition_resolver=(
                transition_resolver if transition_resolver is not None else self.transition_resolver
            ),
        )
        result = await flow_orchestrator.run(request, max_steps=max_steps)
        await self.verification_projection_service.project_flow(result)
        return await self.flow_store.complete_run(
            flow_id=flow_id,
            result=result,
            expected_version=reservation.version,
            lease_id=_active_lease_id(reservation),
        )

    async def heartbeat_flow(
        self,
        *,
        flow_id: UUID,
        lease_id: UUID,
        expected_version: int,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        return await self.flow_store.renew_lease(
            flow_id=flow_id,
            lease_id=lease_id,
            expected_version=expected_version,
            lease_seconds=self.flow_lease_seconds,
        )

    async def recover_flow(
        self,
        *,
        flow_id: UUID,
        expected_version: int,
        request: AgentExecutionRequest,
        recovered_by: str,
        transition_resolver: AgentTransitionRequestResolver | None = None,
        max_steps: int = 10,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        if not self.flow_recovery_enabled:
            raise AgentValidationError("Agent flow recovery is disabled")
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        current = await self.get_flow(flow_id)
        _validate_recovery_request(current, request)
        reservation = await self.flow_store.claim_recovery(
            flow_id=flow_id,
            execution=request,
            expected_version=expected_version,
            recovered_by=recovered_by,
            lease_seconds=self.flow_lease_seconds,
        )
        flow_orchestrator = AgentFlowOrchestrator(
            step_orchestrator=self.orchestrator,
            transition_resolver=(
                transition_resolver if transition_resolver is not None else self.transition_resolver
            ),
        )
        result = await flow_orchestrator.run(request, max_steps=max_steps)
        await self.verification_projection_service.project_flow(result)
        return await self.flow_store.complete_run(
            flow_id=flow_id,
            result=result,
            expected_version=reservation.version,
            lease_id=_active_lease_id(reservation),
        )

    async def execute_claimed_flow(
        self,
        *,
        claim: PersistedAgentFlow,
        request: AgentExecutionRequest,
        transition_resolver: AgentTransitionRequestResolver | None = None,
        max_steps: int = 10,
    ) -> PersistedAgentFlow:
        self._require_flow_store()
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        _validate_claimed_execution(claim, request)
        flow_orchestrator = AgentFlowOrchestrator(
            step_orchestrator=self.orchestrator,
            transition_resolver=(
                transition_resolver if transition_resolver is not None else self.transition_resolver
            ),
        )
        result = await flow_orchestrator.run(request, max_steps=max_steps)
        await self.verification_projection_service.project_flow(result)
        return await self.flow_store.complete_run(
            flow_id=claim.flow_id,
            result=result,
            expected_version=claim.version,
            lease_id=_active_lease_id(claim),
        )

    def _require_flow_store(self) -> None:
        if self.flow_store is None:
            raise RuntimeError("Agent flow persistence is not configured")


def create_agent_platform_service(
    dependencies: AgentDependencyContainer | None = None,
    *,
    transition_resolver: AgentTransitionRequestResolver | None = None,
    flow_store: AgentFlowStore | None = None,
    verification_projection_service: VerificationOpenProjectProjectionService
    | None = None,
    flow_lease_seconds: int = 300,
    flow_recovery_enabled: bool = True,
) -> AgentPlatformService:
    return AgentPlatformService(
        dependencies=dependencies or AgentDependencyContainer(),
        transition_resolver=transition_resolver,
        flow_store=flow_store,
        verification_projection_service=verification_projection_service,
        flow_lease_seconds=flow_lease_seconds,
        flow_recovery_enabled=flow_recovery_enabled,
    )


def _validate_resume_status(flow: PersistedAgentFlow) -> None:
    resumable = {
        AgentFlowStatus.WAITING_FOR_APPROVAL,
        AgentFlowStatus.WAITING_FOR_CLARIFICATION,
        AgentFlowStatus.TRANSITION_PENDING,
        AgentFlowStatus.ESCALATED,
        AgentFlowStatus.MAX_STEPS_EXCEEDED,
    }
    if flow.status not in resumable:
        raise AgentValidationError(f"Agent flow cannot resume from status: {flow.status.value}")


def _validate_resume_request(
    flow: PersistedAgentFlow,
    request: AgentExecutionRequest,
) -> None:
    if request.workflow_id != flow.workflow_id:
        raise AgentValidationError("Resume request must preserve workflow_id")
    if request.request.project_id != flow.project_id:
        raise AgentValidationError("Resume request must preserve project_id")
    expected_agent_type = (
        flow.pending_route.next_agent_type if flow.pending_route is not None else None
    )
    if expected_agent_type and request.agent_type != expected_agent_type:
        raise AgentValidationError(f"Resume request must target agent: {expected_agent_type}")


def _validate_recovery_request(
    flow: PersistedAgentFlow,
    request: AgentExecutionRequest,
) -> None:
    if flow.status != AgentFlowStatus.RUNNING:
        raise AgentValidationError(f"Agent flow cannot recover from status: {flow.status.value}")
    if flow.pending_execution_payload is None:
        raise AgentValidationError("Running flow has no pending execution payload")
    _validate_resume_request(flow, request)
    if request.model_dump(mode="json") != flow.pending_execution_payload:
        raise AgentValidationError(
            "Recovery request must exactly match the pending execution payload"
        )


def _validate_claimed_execution(
    flow: PersistedAgentFlow,
    request: AgentExecutionRequest,
) -> None:
    if flow.status != AgentFlowStatus.RUNNING:
        raise AgentValidationError(f"Agent flow claim is not running: {flow.status.value}")
    if flow.lease is None:
        raise AgentValidationError("Agent flow claim has no active lease")
    _validate_recovery_request(flow, request)


def _lease_owner(prefix: str, request: AgentExecutionRequest) -> str:
    return f"{prefix}:{request.agent_type}:{request.request.execution_id}"


def _active_lease_id(flow: PersistedAgentFlow) -> UUID:
    if flow.lease is None:
        raise RuntimeError("Running agent flow does not have an active lease")
    return flow.lease.lease_id


def _verification_override_id(
    *,
    flow_id: UUID,
    source_result_id: UUID,
    override_reference: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        (
            "ada:verification-override:"
            f"{flow_id}:{source_result_id}:{override_reference}"
        ),
    )
