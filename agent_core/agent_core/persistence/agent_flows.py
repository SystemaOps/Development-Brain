from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.agent_platform.orchestration.contracts import (
    AgentExecutionRequest,
)
from agent_core.agent_platform.orchestration.flow import (
    AgentFlowResult,
    AgentFlowStatus,
)
from agent_core.agent_platform.orchestration.flow_persistence import (
    AgentFlowApproval,
    AgentFlowLease,
    AgentFlowNotFoundError,
    AgentFlowOverrideRecord,
    AgentFlowVersionConflictError,
    PersistedAgentFlow,
    begin_resume_snapshot,
    claim_queued_flow_snapshot,
    close_flow_snapshot,
    complete_override_snapshot,
    complete_run_snapshot,
    escalate_exhausted_recovery_snapshot,
    recover_flow_snapshot,
    recover_pending_flow_snapshot,
    renew_flow_lease_snapshot,
    queue_flow_snapshot,
    reserve_flow_snapshot,
)
from agent_core.models import AgentPlatformFlowRecord


class SqlAlchemyAgentFlowStore:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue(
        self,
        execution: AgentExecutionRequest,
        *,
        max_steps: int = 10,
    ) -> PersistedAgentFlow:
        snapshot = queue_flow_snapshot(execution, max_steps=max_steps)
        record = AgentPlatformFlowRecord(id=snapshot.flow_id)
        _write_snapshot(record, snapshot)
        self.db.add(record)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AgentFlowVersionConflictError(
                f"Agent flow already exists for workflow: {execution.workflow_id}"
            ) from exc
        except Exception:
            await self.db.rollback()
            raise
        return snapshot

    async def reserve(
        self,
        execution: AgentExecutionRequest,
        *,
        lease_owner: str = "local",
        lease_seconds: int = 300,
    ) -> PersistedAgentFlow:
        snapshot = reserve_flow_snapshot(
            execution,
            lease_owner=lease_owner,
            lease_seconds=lease_seconds,
        )
        record = AgentPlatformFlowRecord(id=snapshot.flow_id)
        _write_snapshot(record, snapshot)
        self.db.add(record)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AgentFlowVersionConflictError(
                f"Agent flow already exists for workflow: {execution.workflow_id}"
            ) from exc
        except Exception:
            await self.db.rollback()
            raise
        return snapshot

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
        try:
            record = await self._lock(flow_id)
            current = _read_snapshot(record)
            _check_version(current, expected_version)
            snapshot = begin_resume_snapshot(
                current,
                execution,
                approval=approval,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
            )
            _write_snapshot(record, snapshot)
            await self.db.commit()
            return snapshot
        except Exception:
            await self.db.rollback()
            raise

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
        try:
            record = await self._lock(flow_id)
            current = _read_snapshot(record)
            _check_version(current, expected_version)
            snapshot = recover_flow_snapshot(
                current,
                execution,
                recovered_by=recovered_by,
                lease_seconds=lease_seconds,
                now=now,
            )
            _write_snapshot(record, snapshot)
            await self.db.commit()
            return snapshot
        except Exception:
            await self.db.rollback()
            raise

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
        claimed_at = now or datetime.now(timezone.utc)
        claimable = AgentPlatformFlowRecord.status == AgentFlowStatus.QUEUED.value
        if recover_expired:
            claimable = or_(
                claimable,
                and_(
                    AgentPlatformFlowRecord.status == AgentFlowStatus.RUNNING.value,
                    AgentPlatformFlowRecord.lease_expires_at <= claimed_at,
                ),
            )
        try:
            while True:
                record = await self.db.scalar(
                    select(AgentPlatformFlowRecord)
                    .where(claimable)
                    .order_by(AgentPlatformFlowRecord.updated_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if record is None:
                    await self.db.rollback()
                    return None
                current = _read_snapshot(record)
                if current.status == AgentFlowStatus.QUEUED:
                    snapshot = claim_queued_flow_snapshot(
                        current,
                        worker_id=worker_id,
                        lease_seconds=lease_seconds,
                        now=claimed_at,
                    )
                else:
                    if current.recovery_count >= max_recovery_attempts:
                        snapshot = escalate_exhausted_recovery_snapshot(
                            current,
                            max_recovery_attempts=max_recovery_attempts,
                            now=claimed_at,
                        )
                        _write_snapshot(record, snapshot)
                        await self.db.commit()
                        continue
                    snapshot = recover_pending_flow_snapshot(
                        current,
                        recovered_by=worker_id,
                        lease_seconds=lease_seconds,
                        now=claimed_at,
                    )
                _write_snapshot(record, snapshot)
                await self.db.commit()
                return snapshot
        except Exception:
            await self.db.rollback()
            raise

    async def renew_lease(
        self,
        *,
        flow_id: UUID,
        lease_id: UUID,
        expected_version: int,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> PersistedAgentFlow:
        try:
            record = await self._lock(flow_id)
            current = _read_snapshot(record)
            _check_version(current, expected_version)
            snapshot = renew_flow_lease_snapshot(
                current,
                lease_id=lease_id,
                lease_seconds=lease_seconds,
                now=now,
            )
            _write_snapshot(record, snapshot)
            await self.db.commit()
            return snapshot
        except Exception:
            await self.db.rollback()
            raise

    async def complete_run(
        self,
        *,
        flow_id: UUID,
        result: AgentFlowResult,
        expected_version: int,
        lease_id: UUID,
        now: datetime | None = None,
    ) -> PersistedAgentFlow:
        try:
            record = await self._lock(flow_id)
            current = _read_snapshot(record)
            _check_version(current, expected_version)
            snapshot = complete_run_snapshot(
                current,
                result,
                lease_id=lease_id,
                now=now,
            )
            _write_snapshot(record, snapshot)
            await self.db.commit()
            return snapshot
        except Exception:
            await self.db.rollback()
            raise

    async def close(
        self,
        *,
        flow_id: UUID,
        status: AgentFlowStatus,
        reason: str,
        expected_version: int,
        approval: AgentFlowApproval,
    ) -> PersistedAgentFlow:
        try:
            record = await self._lock(flow_id)
            current = _read_snapshot(record)
            _check_version(current, expected_version)
            snapshot = close_flow_snapshot(
                current,
                status=status,
                reason=reason,
                approval=approval,
            )
            _write_snapshot(record, snapshot)
            await self.db.commit()
            return snapshot
        except Exception:
            await self.db.rollback()
            raise

    async def complete_override(
        self,
        *,
        flow_id: UUID,
        expected_version: int,
        override: AgentFlowOverrideRecord,
    ) -> PersistedAgentFlow:
        try:
            record = await self._lock(flow_id)
            current = _read_snapshot(record)
            _check_version(current, expected_version)
            snapshot = complete_override_snapshot(current, override=override)
            _write_snapshot(record, snapshot)
            await self.db.commit()
            return snapshot
        except Exception:
            await self.db.rollback()
            raise

    async def get(self, flow_id: UUID) -> PersistedAgentFlow | None:
        record = await self.db.get(AgentPlatformFlowRecord, flow_id)
        return _read_snapshot(record) if record is not None else None

    async def get_by_workflow(
        self,
        *,
        project_id: str,
        workflow_id: str,
    ) -> PersistedAgentFlow | None:
        record = await self.db.scalar(
            select(AgentPlatformFlowRecord).where(
                AgentPlatformFlowRecord.project_key == project_id,
                AgentPlatformFlowRecord.workflow_id == workflow_id,
            )
        )
        return _read_snapshot(record) if record is not None else None

    async def _lock(self, flow_id: UUID) -> AgentPlatformFlowRecord:
        record = await self.db.scalar(
            select(AgentPlatformFlowRecord)
            .where(AgentPlatformFlowRecord.id == flow_id)
            .with_for_update()
        )
        if record is None:
            raise AgentFlowNotFoundError(f"Agent flow not found: {flow_id}")
        return record


def _read_snapshot(record: AgentPlatformFlowRecord) -> PersistedAgentFlow:
    payload = dict(record.flow_json)
    if record.lease_id is not None:
        payload["lease"] = AgentFlowLease(
            lease_id=record.lease_id,
            owner=record.lease_owner or "migration-recovery",
            acquired_at=record.lease_acquired_at or record.updated_at,
            expires_at=record.lease_expires_at or record.updated_at,
        ).model_dump(mode="json")
    else:
        payload["lease"] = None
    payload["recovery_count"] = record.recovery_count
    return PersistedAgentFlow.model_validate(payload)


def _write_snapshot(
    record: AgentPlatformFlowRecord,
    snapshot: PersistedAgentFlow,
) -> None:
    pending_execution = snapshot.pending_execution_payload or {}
    pending_request = pending_execution.get("request", {})
    current_step = snapshot.steps[-1] if snapshot.steps else None
    pending_route = snapshot.pending_route
    latest_approval = snapshot.approvals[-1] if snapshot.approvals else None

    record.workflow_id = snapshot.workflow_id
    record.project_key = snapshot.project_id
    record.task_key = snapshot.task_id
    record.status = snapshot.status.value
    record.version = snapshot.version
    record.step_count = snapshot.step_count
    record.current_agent_type = pending_execution.get("agent_type") or (
        current_step.agent_type if current_step else None
    )
    current_execution_id = pending_request.get("execution_id")
    record.current_execution_id = (
        UUID(str(current_execution_id))
        if current_execution_id
        else current_step.execution_id
        if current_step
        else None
    )
    record.pending_action = pending_route.next_action.value if pending_route is not None else None
    record.pending_agent_type = pending_route.next_agent_type if pending_route is not None else None
    record.requires_approval = (
        pending_route.requires_approval if pending_route is not None else False
    )
    record.correlation_id = snapshot.correlation_id
    record.resume_count = snapshot.resume_count
    record.recovery_count = snapshot.recovery_count
    record.lease_id = snapshot.lease.lease_id if snapshot.lease is not None else None
    record.lease_owner = snapshot.lease.owner if snapshot.lease is not None else None
    record.lease_acquired_at = snapshot.lease.acquired_at if snapshot.lease is not None else None
    record.lease_expires_at = snapshot.lease.expires_at if snapshot.lease is not None else None
    record.last_approval_decision = (
        latest_approval.decision.value if latest_approval is not None else None
    )
    record.flow_json = snapshot.model_dump(mode="json")
    record.created_at = snapshot.created_at
    record.updated_at = snapshot.updated_at


def _check_version(current: PersistedAgentFlow, expected_version: int) -> None:
    if current.version != expected_version:
        raise AgentFlowVersionConflictError(
            f"Agent flow version conflict: expected {expected_version}, found {current.version}"
        )
