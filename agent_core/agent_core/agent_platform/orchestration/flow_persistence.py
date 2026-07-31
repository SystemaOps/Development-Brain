from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_core.agent_platform.agents.base.contracts import (
    AgentNextAction,
    AgentRunStatus,
)
from agent_core.agent_platform.orchestration.contracts import (
    AgentExecutionRequest,
)
from agent_core.agent_platform.orchestration.flow import (
    AgentFlowResult,
    AgentFlowStatus,
)
from agent_core.agent_platform.orchestration.routing import AgentRouteDecision
from agent_core.domain.enums import ApprovalDecision


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentFlowPersistenceError(RuntimeError):
    pass


class AgentFlowNotFoundError(AgentFlowPersistenceError):
    pass


class AgentFlowVersionConflictError(AgentFlowPersistenceError):
    pass


class AgentFlowLeaseConflictError(AgentFlowPersistenceError):
    pass


class AgentFlowApproval(BaseModel):
    decision: ApprovalDecision
    approval_reference: str = Field(min_length=1)
    actor: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utc_now)


class AgentFlowOverrideRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    override_id: UUID = Field(default_factory=uuid4)
    override_type: str = Field(min_length=1, max_length=120)
    source_step_sequence: int = Field(ge=1)
    source_agent_type: str = Field(min_length=1)
    source_execution_id: UUID
    source_result_id: UUID
    original_status: AgentRunStatus
    original_next_action: AgentNextAction
    original_outcome: str = Field(min_length=1)
    finding_codes: list[str] = Field(default_factory=list)
    affected_item_keys: list[str] = Field(default_factory=list)
    actor: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=4000)
    override_reference: str = Field(min_length=1, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utc_now)


class AgentFlowLease(BaseModel):
    lease_id: UUID = Field(default_factory=uuid4)
    owner: str = Field(min_length=1, max_length=160)
    acquired_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime


class AgentFlowRecoveryRecord(BaseModel):
    sequence: int = Field(ge=1)
    execution_id: UUID
    recovered_by: str = Field(min_length=1, max_length=160)
    recovered_at: datetime = Field(default_factory=_utc_now)
    previous_lease: AgentFlowLease
    replacement_lease: AgentFlowLease


class AgentFlowExecutionOptions(BaseModel):
    max_steps: int = Field(default=10, ge=1, le=100)


class AgentFlowStepRecord(BaseModel):
    sequence: int = Field(ge=1)
    agent_type: str
    execution_id: UUID
    result_id: UUID
    status: AgentRunStatus
    next_action: AgentNextAction
    request_payload: dict[str, Any]
    result_payload: dict[str, Any]
    route: AgentRouteDecision


class PersistedAgentFlow(BaseModel):
    flow_id: UUID
    workflow_id: str
    project_id: str
    task_id: str | None = None
    status: AgentFlowStatus
    version: int = Field(ge=1)
    step_count: int = Field(default=0, ge=0)
    steps: list[AgentFlowStepRecord] = Field(default_factory=list)
    pending_route: AgentRouteDecision | None = None
    pending_execution_payload: dict[str, Any] | None = None
    reason: str
    correlation_id: str
    resume_count: int = Field(default=0, ge=0)
    recovery_count: int = Field(default=0, ge=0)
    approvals: list[AgentFlowApproval] = Field(default_factory=list)
    overrides: list[AgentFlowOverrideRecord] = Field(default_factory=list)
    lease: AgentFlowLease | None = None
    recoveries: list[AgentFlowRecoveryRecord] = Field(default_factory=list)
    execution_options: AgentFlowExecutionOptions = Field(default_factory=AgentFlowExecutionOptions)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


@runtime_checkable
class AgentFlowStore(Protocol):
    async def enqueue(
        self,
        execution: AgentExecutionRequest,
        *,
        max_steps: int = 10,
    ) -> PersistedAgentFlow: ...

    async def reserve(
        self,
        execution: AgentExecutionRequest,
        *,
        lease_owner: str = "local",
        lease_seconds: int = 300,
    ) -> PersistedAgentFlow: ...

    async def begin_resume(
        self,
        *,
        flow_id: UUID,
        execution: AgentExecutionRequest,
        expected_version: int,
        approval: AgentFlowApproval | None = None,
        lease_owner: str = "local",
        lease_seconds: int = 300,
    ) -> PersistedAgentFlow: ...

    async def claim_recovery(
        self,
        *,
        flow_id: UUID,
        execution: AgentExecutionRequest,
        expected_version: int,
        recovered_by: str,
        lease_seconds: int = 300,
    ) -> PersistedAgentFlow: ...

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        recover_expired: bool = True,
        max_recovery_attempts: int = 3,
    ) -> PersistedAgentFlow | None: ...

    async def renew_lease(
        self,
        *,
        flow_id: UUID,
        lease_id: UUID,
        expected_version: int,
        lease_seconds: int = 300,
    ) -> PersistedAgentFlow: ...

    async def complete_run(
        self,
        *,
        flow_id: UUID,
        result: AgentFlowResult,
        expected_version: int,
        lease_id: UUID,
        now: datetime | None = None,
    ) -> PersistedAgentFlow: ...

    async def close(
        self,
        *,
        flow_id: UUID,
        status: AgentFlowStatus,
        reason: str,
        expected_version: int,
        approval: AgentFlowApproval,
    ) -> PersistedAgentFlow: ...

    async def complete_override(
        self,
        *,
        flow_id: UUID,
        expected_version: int,
        override: AgentFlowOverrideRecord,
    ) -> PersistedAgentFlow: ...

    async def get(self, flow_id: UUID) -> PersistedAgentFlow | None: ...

    async def get_by_workflow(
        self,
        *,
        project_id: str,
        workflow_id: str,
    ) -> PersistedAgentFlow | None: ...


class InMemoryAgentFlowStore:
    def __init__(self) -> None:
        self.flows: dict[UUID, PersistedAgentFlow] = {}
        self.workflow_index: dict[tuple[str, str], UUID] = {}

    async def enqueue(
        self,
        execution: AgentExecutionRequest,
        *,
        max_steps: int = 10,
    ) -> PersistedAgentFlow:
        identity = (
            execution.request.project_id,
            execution.workflow_id,
        )
        if identity in self.workflow_index:
            raise AgentFlowVersionConflictError(
                f"Agent flow already exists for workflow: {execution.workflow_id}"
            )
        snapshot = queue_flow_snapshot(execution, max_steps=max_steps)
        self.flows[snapshot.flow_id] = snapshot
        self.workflow_index[identity] = snapshot.flow_id
        return snapshot.model_copy(deep=True)

    async def reserve(
        self,
        execution: AgentExecutionRequest,
        *,
        lease_owner: str = "local",
        lease_seconds: int = 300,
    ) -> PersistedAgentFlow:
        identity = (
            execution.request.project_id,
            execution.workflow_id,
        )
        if identity in self.workflow_index:
            raise AgentFlowVersionConflictError(
                f"Agent flow already exists for workflow: {execution.workflow_id}"
            )
        snapshot = reserve_flow_snapshot(
            execution,
            lease_owner=lease_owner,
            lease_seconds=lease_seconds,
        )
        self.flows[snapshot.flow_id] = snapshot
        self.workflow_index[identity] = snapshot.flow_id
        return snapshot.model_copy(deep=True)

    async def begin_resume(
        self,
        *,
        flow_id: UUID,
        execution: AgentExecutionRequest,
        expected_version: int,
        approval: AgentFlowApproval | None = None,
        lease_owner: str = "local",
        lease_seconds: int = 300,
    ) -> PersistedAgentFlow:
        current = self._require(flow_id)
        _check_version(current, expected_version)
        snapshot = begin_resume_snapshot(
            current,
            execution,
            approval=approval,
            lease_owner=lease_owner,
            lease_seconds=lease_seconds,
        )
        self.flows[flow_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def claim_recovery(
        self,
        *,
        flow_id: UUID,
        execution: AgentExecutionRequest,
        expected_version: int,
        recovered_by: str,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> PersistedAgentFlow:
        current = self._require(flow_id)
        _check_version(current, expected_version)
        snapshot = recover_flow_snapshot(
            current,
            execution,
            recovered_by=recovered_by,
            lease_seconds=lease_seconds,
            now=now,
        )
        self.flows[flow_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        recover_expired: bool = True,
        max_recovery_attempts: int = 3,
        now: datetime | None = None,
    ) -> PersistedAgentFlow | None:
        if max_recovery_attempts < 0:
            raise ValueError("max_recovery_attempts cannot be negative")
        claimed_at = now or _utc_now()
        candidates = sorted(
            self.flows.values(),
            key=lambda flow: flow.updated_at,
        )
        for current in candidates:
            if current.status == AgentFlowStatus.QUEUED:
                snapshot = claim_queued_flow_snapshot(
                    current,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    now=claimed_at,
                )
            elif (
                recover_expired
                and current.status == AgentFlowStatus.RUNNING
                and current.lease is not None
                and current.lease.expires_at <= claimed_at
            ):
                if current.recovery_count >= max_recovery_attempts:
                    snapshot = escalate_exhausted_recovery_snapshot(
                        current,
                        max_recovery_attempts=max_recovery_attempts,
                        now=claimed_at,
                    )
                    self.flows[current.flow_id] = snapshot
                    continue
                snapshot = recover_pending_flow_snapshot(
                    current,
                    recovered_by=worker_id,
                    lease_seconds=lease_seconds,
                    now=claimed_at,
                )
            else:
                continue
            self.flows[current.flow_id] = snapshot
            return snapshot.model_copy(deep=True)
        return None

    async def renew_lease(
        self,
        *,
        flow_id: UUID,
        lease_id: UUID,
        expected_version: int,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> PersistedAgentFlow:
        current = self._require(flow_id)
        _check_version(current, expected_version)
        snapshot = renew_flow_lease_snapshot(
            current,
            lease_id=lease_id,
            lease_seconds=lease_seconds,
            now=now,
        )
        self.flows[flow_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def complete_run(
        self,
        *,
        flow_id: UUID,
        result: AgentFlowResult,
        expected_version: int,
        lease_id: UUID,
        now: datetime | None = None,
    ) -> PersistedAgentFlow:
        current = self._require(flow_id)
        _check_version(current, expected_version)
        snapshot = complete_run_snapshot(
            current,
            result,
            lease_id=lease_id,
            now=now,
        )
        self.flows[flow_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def close(
        self,
        *,
        flow_id: UUID,
        status: AgentFlowStatus,
        reason: str,
        expected_version: int,
        approval: AgentFlowApproval,
    ) -> PersistedAgentFlow:
        current = self._require(flow_id)
        _check_version(current, expected_version)
        snapshot = close_flow_snapshot(
            current,
            status=status,
            reason=reason,
            approval=approval,
        )
        self.flows[flow_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def complete_override(
        self,
        *,
        flow_id: UUID,
        expected_version: int,
        override: AgentFlowOverrideRecord,
    ) -> PersistedAgentFlow:
        current = self._require(flow_id)
        _check_version(current, expected_version)
        snapshot = complete_override_snapshot(current, override=override)
        self.flows[flow_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def get(self, flow_id: UUID) -> PersistedAgentFlow | None:
        snapshot = self.flows.get(flow_id)
        return snapshot.model_copy(deep=True) if snapshot is not None else None

    async def get_by_workflow(
        self,
        *,
        project_id: str,
        workflow_id: str,
    ) -> PersistedAgentFlow | None:
        flow_id = self.workflow_index.get((project_id, workflow_id))
        return await self.get(flow_id) if flow_id is not None else None

    def _require(self, flow_id: UUID) -> PersistedAgentFlow:
        snapshot = self.flows.get(flow_id)
        if snapshot is None:
            raise AgentFlowNotFoundError(f"Agent flow not found: {flow_id}")
        return snapshot


def reserve_flow_snapshot(
    execution: AgentExecutionRequest,
    *,
    flow_id: UUID | None = None,
    lease_owner: str = "local",
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    acquired_at = now or _utc_now()
    return PersistedAgentFlow(
        flow_id=flow_id or uuid4(),
        workflow_id=execution.workflow_id,
        project_id=execution.request.project_id,
        task_id=execution.request.task_id,
        status=AgentFlowStatus.RUNNING,
        version=1,
        pending_execution_payload=execution.model_dump(mode="json"),
        reason="Flow execution reserved.",
        correlation_id=execution.correlation_id,
        lease=_new_lease(
            owner=lease_owner,
            lease_seconds=lease_seconds,
            acquired_at=acquired_at,
        ),
        created_at=acquired_at,
        updated_at=acquired_at,
    )


def queue_flow_snapshot(
    execution: AgentExecutionRequest,
    *,
    flow_id: UUID | None = None,
    max_steps: int = 10,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    queued_at = now or _utc_now()
    return PersistedAgentFlow(
        flow_id=flow_id or uuid4(),
        workflow_id=execution.workflow_id,
        project_id=execution.request.project_id,
        task_id=execution.request.task_id,
        status=AgentFlowStatus.QUEUED,
        version=1,
        pending_execution_payload=execution.model_dump(mode="json"),
        reason="Flow queued for background execution.",
        correlation_id=execution.correlation_id,
        execution_options=AgentFlowExecutionOptions(max_steps=max_steps),
        created_at=queued_at,
        updated_at=queued_at,
    )


def claim_queued_flow_snapshot(
    current: PersistedAgentFlow,
    *,
    worker_id: str,
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.QUEUED:
        raise AgentFlowPersistenceError(
            f"Only a queued flow can be claimed, found: {current.status.value}"
        )
    if current.pending_execution_payload is None:
        raise AgentFlowPersistenceError("Queued flow has no pending execution payload")
    claimed_at = now or _utc_now()
    return current.model_copy(
        deep=True,
        update={
            "status": AgentFlowStatus.RUNNING,
            "version": current.version + 1,
            "lease": _new_lease(
                owner=worker_id,
                lease_seconds=lease_seconds,
                acquired_at=claimed_at,
            ),
            "reason": f"Queued flow claimed by {worker_id}.",
            "updated_at": claimed_at,
        },
    )


def begin_resume_snapshot(
    current: PersistedAgentFlow,
    execution: AgentExecutionRequest,
    *,
    approval: AgentFlowApproval | None = None,
    lease_owner: str = "local",
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    resumable = {
        AgentFlowStatus.WAITING_FOR_APPROVAL,
        AgentFlowStatus.WAITING_FOR_CLARIFICATION,
        AgentFlowStatus.TRANSITION_PENDING,
        AgentFlowStatus.ESCALATED,
        AgentFlowStatus.MAX_STEPS_EXCEEDED,
    }
    if current.status not in resumable:
        raise AgentFlowPersistenceError(
            f"Agent flow cannot resume from status: {current.status.value}"
        )
    if current.status == AgentFlowStatus.WAITING_FOR_APPROVAL:
        if approval is None or approval.decision != ApprovalDecision.APPROVED:
            raise AgentFlowPersistenceError(
                "An approved decision is required to claim an approval-gated flow"
            )
    elif approval is not None:
        raise AgentFlowPersistenceError(
            "Approval evidence is only valid for a flow waiting for approval"
        )
    _validate_execution_identity(current, execution)
    approvals = [*current.approvals]
    if approval is not None:
        approvals.append(approval)
    acquired_at = now or _utc_now()
    return current.model_copy(
        deep=True,
        update={
            "task_id": execution.request.task_id or current.task_id,
            "status": AgentFlowStatus.RUNNING,
            "version": current.version + 1,
            "pending_route": None,
            "pending_execution_payload": execution.model_dump(mode="json"),
            "reason": "Flow resume reserved.",
            "resume_count": current.resume_count + 1,
            "approvals": approvals,
            "lease": _new_lease(
                owner=lease_owner,
                lease_seconds=lease_seconds,
                acquired_at=acquired_at,
            ),
            "updated_at": acquired_at,
        },
    )


def recover_flow_snapshot(
    current: PersistedAgentFlow,
    execution: AgentExecutionRequest,
    *,
    recovered_by: str,
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.RUNNING:
        raise AgentFlowPersistenceError(
            f"Only a running flow can be recovered, found: {current.status.value}"
        )
    if current.lease is None:
        raise AgentFlowPersistenceError("Running flow does not have a recovery lease")
    recovered_at = now or _utc_now()
    if current.lease.expires_at > recovered_at:
        raise AgentFlowLeaseConflictError(
            f"Agent flow lease is active until {current.lease.expires_at.isoformat()}"
        )
    _validate_execution_identity(current, execution)
    execution_payload = execution.model_dump(mode="json")
    if execution_payload != current.pending_execution_payload:
        raise AgentFlowPersistenceError(
            "Recovery request must exactly match the pending execution payload"
        )
    return recover_pending_flow_snapshot(
        current,
        recovered_by=recovered_by,
        lease_seconds=lease_seconds,
        now=recovered_at,
    )


def recover_pending_flow_snapshot(
    current: PersistedAgentFlow,
    *,
    recovered_by: str,
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.RUNNING:
        raise AgentFlowPersistenceError(
            f"Only a running flow can be recovered, found: {current.status.value}"
        )
    if current.lease is None:
        raise AgentFlowPersistenceError("Running flow does not have a recovery lease")
    if current.pending_execution_payload is None:
        raise AgentFlowPersistenceError("Running flow has no pending execution payload")
    recovered_at = now or _utc_now()
    if current.lease.expires_at > recovered_at:
        raise AgentFlowLeaseConflictError(
            f"Agent flow lease is active until {current.lease.expires_at.isoformat()}"
        )
    execution_id = current.pending_execution_payload.get("request", {}).get("execution_id")
    if execution_id is None:
        raise AgentFlowPersistenceError("Pending execution payload has no execution_id")
    replacement_lease = _new_lease(
        owner=recovered_by,
        lease_seconds=lease_seconds,
        acquired_at=recovered_at,
    )
    recovery = AgentFlowRecoveryRecord(
        sequence=current.recovery_count + 1,
        execution_id=UUID(str(execution_id)),
        recovered_by=recovered_by,
        recovered_at=recovered_at,
        previous_lease=current.lease,
        replacement_lease=replacement_lease,
    )
    return current.model_copy(
        deep=True,
        update={
            "version": current.version + 1,
            "recovery_count": current.recovery_count + 1,
            "recoveries": [*current.recoveries, recovery],
            "lease": replacement_lease,
            "reason": f"Expired flow lease recovered by {recovered_by}.",
            "updated_at": recovered_at,
        },
    )


def escalate_exhausted_recovery_snapshot(
    current: PersistedAgentFlow,
    *,
    max_recovery_attempts: int,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.RUNNING:
        raise AgentFlowPersistenceError(
            f"Only a running flow can exhaust recovery, found: {current.status.value}"
        )
    if max_recovery_attempts < 0:
        raise ValueError("max_recovery_attempts cannot be negative")
    if current.recovery_count < max_recovery_attempts:
        raise AgentFlowPersistenceError(
            "Agent flow has not exhausted its automatic recovery attempts"
        )
    escalated_at = now or _utc_now()
    return current.model_copy(
        deep=True,
        update={
            "status": AgentFlowStatus.ESCALATED,
            "version": current.version + 1,
            "lease": None,
            "reason": (
                "Automatic recovery attempts exhausted "
                f"({max_recovery_attempts}); human intervention is required."
            ),
            "updated_at": escalated_at,
        },
    )


def renew_flow_lease_snapshot(
    current: PersistedAgentFlow,
    *,
    lease_id: UUID,
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.RUNNING:
        raise AgentFlowPersistenceError(
            f"Only a running flow lease can be renewed, found: {current.status.value}"
        )
    renewed_at = now or _utc_now()
    lease = _require_lease(current, lease_id)
    if lease.expires_at <= renewed_at:
        raise AgentFlowLeaseConflictError("Expired flow lease cannot be renewed")
    renewed_lease = lease.model_copy(
        update={
            "expires_at": max(
                lease.expires_at,
                _lease_expiry(renewed_at, lease_seconds),
            ),
        }
    )
    return current.model_copy(
        deep=True,
        update={
            "lease": renewed_lease,
            "updated_at": renewed_at,
        },
    )


def complete_run_snapshot(
    current: PersistedAgentFlow,
    result: AgentFlowResult,
    *,
    lease_id: UUID,
    now: datetime | None = None,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.RUNNING:
        raise AgentFlowPersistenceError("Only a running flow can complete an execution")
    completed_at = now or _utc_now()
    _require_active_lease(current, lease_id, at=completed_at)
    if result.workflow_id != current.workflow_id:
        raise AgentFlowPersistenceError("Completed flow must preserve workflow_id")
    if not result.steps:
        raise AgentFlowPersistenceError("Cannot complete an agent flow without steps")
    project_id = result.steps[0].execution.request.project_id
    if project_id != current.project_id:
        raise AgentFlowPersistenceError("Completed flow must preserve project_id")

    new_steps = _step_records(result, sequence_offset=current.step_count)
    return current.model_copy(
        deep=True,
        update={
            "task_id": _latest_task_id(result) or current.task_id,
            "status": result.status,
            "version": current.version + 1,
            "step_count": current.step_count + len(new_steps),
            "steps": [*current.steps, *new_steps],
            "pending_route": result.pending_route,
            "pending_execution_payload": None,
            "lease": None,
            "reason": result.reason,
            "updated_at": completed_at,
        },
    )


def close_flow_snapshot(
    current: PersistedAgentFlow,
    *,
    status: AgentFlowStatus,
    reason: str,
    approval: AgentFlowApproval,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.WAITING_FOR_APPROVAL:
        raise AgentFlowPersistenceError(
            "Only a flow waiting for approval can be closed by approval decision"
        )
    if status not in {
        AgentFlowStatus.CHANGES_REQUESTED,
        AgentFlowStatus.CANCELLED,
    }:
        raise AgentFlowPersistenceError(f"Unsupported approval close status: {status}")
    expected_status = {
        ApprovalDecision.CHANGES_REQUESTED: AgentFlowStatus.CHANGES_REQUESTED,
        ApprovalDecision.CANCELLED: AgentFlowStatus.CANCELLED,
    }.get(approval.decision)
    if expected_status != status:
        raise AgentFlowPersistenceError(
            "Approval decision does not match the requested close status"
        )
    return current.model_copy(
        deep=True,
        update={
            "status": status,
            "version": current.version + 1,
            "pending_route": None,
            "pending_execution_payload": None,
            "lease": None,
            "reason": reason,
            "resume_count": current.resume_count + 1,
            "approvals": [*current.approvals, approval],
            "updated_at": _utc_now(),
        },
    )


def complete_override_snapshot(
    current: PersistedAgentFlow,
    *,
    override: AgentFlowOverrideRecord,
) -> PersistedAgentFlow:
    if current.status != AgentFlowStatus.WAITING_FOR_APPROVAL:
        raise AgentFlowPersistenceError(
            "Only a flow waiting for approval can be completed by override"
        )
    if not current.steps:
        raise AgentFlowPersistenceError("Override requires a persisted source step")
    source = current.steps[-1]
    if (
        override.source_step_sequence != source.sequence
        or override.source_agent_type != source.agent_type
        or override.source_execution_id != source.execution_id
        or override.source_result_id != source.result_id
    ):
        raise AgentFlowPersistenceError(
            "Override source identity must match the latest persisted flow step"
        )
    if any(
        existing.override_reference == override.override_reference for existing in current.overrides
    ):
        raise AgentFlowPersistenceError(
            f"Override reference already exists: {override.override_reference}"
        )

    return current.model_copy(
        deep=True,
        update={
            "status": AgentFlowStatus.COMPLETED,
            "version": current.version + 1,
            "pending_route": None,
            "pending_execution_payload": None,
            "lease": None,
            "reason": (
                f"Flow completed by {override.override_type} override "
                f"from {override.actor}: {override.reason}"
            ),
            "overrides": [*current.overrides, override],
            "updated_at": override.recorded_at,
        },
    )


def _step_records(
    result: AgentFlowResult,
    *,
    sequence_offset: int = 0,
) -> list[AgentFlowStepRecord]:
    return [
        AgentFlowStepRecord(
            sequence=sequence_offset + index,
            agent_type=step.execution.agent_type,
            execution_id=step.execution.request.execution_id,
            result_id=step.outcome.persisted.result_id,
            status=step.outcome.result.status,
            next_action=step.outcome.result.next_action,
            request_payload=step.execution.model_dump(mode="json"),
            result_payload=step.outcome.result.model_dump(mode="json"),
            route=step.outcome.route,
        )
        for index, step in enumerate(result.steps, start=1)
    ]


def _latest_task_id(result: AgentFlowResult) -> str | None:
    for step in reversed(result.steps):
        if step.outcome.result.task_id:
            return step.outcome.result.task_id
        if step.execution.request.task_id:
            return step.execution.request.task_id
    return None


def _validate_execution_identity(
    current: PersistedAgentFlow,
    execution: AgentExecutionRequest,
) -> None:
    if execution.workflow_id != current.workflow_id:
        raise AgentFlowPersistenceError("Resumed flow must preserve workflow_id")
    if execution.request.project_id != current.project_id:
        raise AgentFlowPersistenceError("Resumed flow must preserve project_id")


def _new_lease(
    *,
    owner: str,
    lease_seconds: int,
    acquired_at: datetime,
) -> AgentFlowLease:
    if not owner.strip():
        raise AgentFlowPersistenceError("Flow lease owner cannot be blank")
    if len(owner) > 160:
        raise AgentFlowPersistenceError("Flow lease owner cannot exceed 160 characters")
    return AgentFlowLease(
        owner=owner,
        acquired_at=acquired_at,
        expires_at=_lease_expiry(acquired_at, lease_seconds),
    )


def _lease_expiry(started_at: datetime, lease_seconds: int) -> datetime:
    if lease_seconds < 1:
        raise AgentFlowPersistenceError("Flow lease duration must be at least 1 second")
    return started_at + timedelta(seconds=lease_seconds)


def _require_lease(
    current: PersistedAgentFlow,
    lease_id: UUID,
) -> AgentFlowLease:
    if current.lease is None:
        raise AgentFlowLeaseConflictError("Agent flow does not have an active lease")
    if current.lease.lease_id != lease_id:
        raise AgentFlowLeaseConflictError("Agent flow lease token does not match")
    return current.lease


def _require_active_lease(
    current: PersistedAgentFlow,
    lease_id: UUID,
    *,
    at: datetime,
) -> AgentFlowLease:
    lease = _require_lease(current, lease_id)
    if lease.expires_at <= at:
        raise AgentFlowLeaseConflictError("Expired flow lease cannot complete execution")
    return lease


def _check_version(current: PersistedAgentFlow, expected_version: int) -> None:
    if current.version != expected_version:
        raise AgentFlowVersionConflictError(
            f"Agent flow version conflict: expected {expected_version}, found {current.version}"
        )
