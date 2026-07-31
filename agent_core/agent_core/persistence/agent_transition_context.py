from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.agent_platform.agents.base.contracts import ArtifactReference
from agent_core.agent_platform.orchestration.transition_context import (
    AgentTaskTransitionContext,
)
from agent_core.domain.coding import CodingAttemptRequest, CodingAttemptResult
from agent_core.domain.enums import (
    ApprovalDecision,
    ApprovalScope,
    PlanNodeKind,
    PlanVersionStatus,
)
from agent_core.models import (
    AgentPlatformCheckpointRecord,
    AgentPlatformResultRecord,
    ApprovalRecord,
    CodingAttemptRecord,
    ContextCapsule,
    ExternalArtifact,
    PlanNode,
    PlanNodeIdentity,
    PlanVersion,
    Project,
)
from agent_core.schemas import AcceptanceCriterionSpec


class SqlAlchemyAgentTransitionContextStore:
    """Loads cross-agent handoff context from existing durable records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def load_task_context(
        self,
        *,
        project_id: str,
        task_id: str,
        workflow_id: str,
        plan_version_id: str | None = None,
    ) -> AgentTaskTransitionContext | None:
        project = await self.db.scalar(select(Project).where(Project.project_key == project_id))
        if project is None:
            return None

        task_filters = [
            PlanNode.project_id == project.id,
            PlanNode.kind == PlanNodeKind.TASK.value,
            PlanNodeIdentity.stable_key == task_id,
        ]
        if plan_version_id is not None:
            try:
                task_filters.append(PlanVersion.id == UUID(plan_version_id))
            except ValueError:
                return None

        task_row = (
            await self.db.execute(
                select(PlanNode, PlanNodeIdentity, PlanVersion)
                .join(
                    PlanNodeIdentity,
                    PlanNodeIdentity.id == PlanNode.node_identity_id,
                )
                .join(PlanVersion, PlanVersion.id == PlanNode.plan_version_id)
                .where(*task_filters)
                .order_by(PlanVersion.version_number.desc())
                .limit(1)
            )
        ).first()
        if task_row is None:
            return None
        node, identity, version = task_row

        capsules = list(
            (
                await self.db.scalars(
                    select(ContextCapsule)
                    .where(ContextCapsule.plan_node_id == node.id)
                    .order_by(ContextCapsule.created_at.desc())
                )
            ).all()
        )
        external_artifacts = list(
            (
                await self.db.scalars(
                    select(ExternalArtifact)
                    .where(ExternalArtifact.node_identity_id == identity.id)
                    .order_by(ExternalArtifact.created_at.desc())
                )
            ).all()
        )
        approval = await self.db.scalar(
            select(ApprovalRecord)
            .where(
                ApprovalRecord.project_id == project.id,
                ApprovalRecord.approval_scope == ApprovalScope.PLANNING.value,
                or_(
                    ApprovalRecord.plan_version_id == version.id,
                    ApprovalRecord.plan_version_id.is_(None),
                ),
            )
            .order_by(ApprovalRecord.decided_at.desc())
            .limit(1)
        )

        checkpoint = await self.db.scalar(
            select(AgentPlatformCheckpointRecord)
            .where(
                AgentPlatformCheckpointRecord.project_key == project_id,
                AgentPlatformCheckpointRecord.workflow_id == workflow_id,
                AgentPlatformCheckpointRecord.agent_type == "coding",
                AgentPlatformCheckpointRecord.thread_id == f"{project_id}:{task_id}:coding",
            )
            .order_by(AgentPlatformCheckpointRecord.updated_at.desc())
            .limit(1)
        )
        result_record = await self.db.scalar(
            select(AgentPlatformResultRecord)
            .where(
                AgentPlatformResultRecord.project_key == project_id,
                AgentPlatformResultRecord.task_key == task_id,
                AgentPlatformResultRecord.agent_type == "coding",
            )
            .order_by(AgentPlatformResultRecord.created_at.desc())
            .limit(1)
        )
        attempt_record = await self.db.scalar(
            select(CodingAttemptRecord)
            .where(
                CodingAttemptRecord.project_id == project.id,
                CodingAttemptRecord.task_key == task_id,
            )
            .order_by(CodingAttemptRecord.attempt_number.desc())
            .limit(1)
        )

        prepared_coding_attempt = _attempt_from_capsules(
            capsules,
            "prepared_coding_attempt",
            "coding_attempt",
        )
        prepared_rework_attempt = _attempt_from_capsules(
            capsules,
            "prepared_rework_attempt",
            "rework_coding_attempt",
        )
        latest_coding_attempt = _attempt_from_checkpoint(checkpoint)
        latest_coding_result = _result_from_platform_record(result_record)
        if latest_coding_result is None:
            latest_coding_result = _result_from_attempt_record(attempt_record)

        approval_decision = approval.decision if approval is not None else None
        planning_approved = version.status in {
            PlanVersionStatus.APPROVED.value,
            PlanVersionStatus.ACTIVE.value,
        }
        if approval_decision is not None:
            planning_approved = approval_decision == ApprovalDecision.APPROVED.value

        node_payload = node.node_json or {}
        acceptance_criteria = [
            AcceptanceCriterionSpec.model_validate(item)
            for item in node_payload.get("acceptance_criteria", [])
        ]
        return AgentTaskTransitionContext(
            task_id=identity.stable_key,
            objective=node.objective,
            acceptance_criteria=acceptance_criteria,
            input_artifacts=_artifact_references(capsules, external_artifacts),
            planning_approved=planning_approved,
            prepared_coding_attempt=prepared_coding_attempt,
            prepared_rework_attempt=prepared_rework_attempt,
            latest_coding_attempt=latest_coding_attempt,
            latest_coding_result=latest_coding_result,
            metadata={
                "project_record_id": str(project.id),
                "plan_version_id": str(version.id),
                "plan_version_number": version.version_number,
                "plan_version_status": version.status,
                "plan_node_id": str(node.id),
                "plan_node_identity_id": str(identity.id),
                "approval_decision": approval_decision,
                "context_capsule_ids": [str(item.id) for item in capsules],
            },
        )


def _attempt_from_capsules(
    capsules: list[ContextCapsule],
    *keys: str,
) -> CodingAttemptRequest | None:
    for capsule in capsules:
        payload = capsule.capsule_json or {}
        for key in keys:
            if payload.get(key) is not None:
                return CodingAttemptRequest.model_validate(payload[key])
    return None


def _attempt_from_checkpoint(
    checkpoint: AgentPlatformCheckpointRecord | None,
) -> CodingAttemptRequest | None:
    if checkpoint is None:
        return None
    payload = checkpoint.state_json or {}
    coding_attempt = payload.get("coding_attempt")
    if coding_attempt is None:
        return None
    return CodingAttemptRequest.model_validate(coding_attempt)


def _result_from_platform_record(
    record: AgentPlatformResultRecord | None,
) -> CodingAttemptResult | None:
    if record is None:
        return None
    coding_result = (record.result_json or {}).get("coding_result")
    if coding_result is None:
        return None
    return CodingAttemptResult.model_validate(coding_result)


def _result_from_attempt_record(
    record: CodingAttemptRecord | None,
) -> CodingAttemptResult | None:
    if record is None:
        return None
    return CodingAttemptResult.model_validate(
        {
            "task_key": record.task_key,
            "repository_key": record.repository_key,
            "attempt_number": record.attempt_number,
            "status": record.status,
            "base_commit_sha": record.base_commit_sha,
            "branch": record.branch,
            "changed_files": record.changed_files or [],
            "command_results": record.command_results or [],
            "final_diff": record.final_diff or "",
            "rollback_plan": record.rollback_plan,
            "errors": (record.error_summary or {}).get("errors", []),
            "evidence": record.evidence or [],
        }
    )


def _artifact_references(
    capsules: list[ContextCapsule],
    external_artifacts: list[ExternalArtifact],
) -> list[ArtifactReference]:
    artifacts = [
        ArtifactReference(
            artifact_id=f"context-capsule:{capsule.id}",
            artifact_type="context_capsule",
            uri=f"postgres://context_capsules/{capsule.id}",
            title=f"{capsule.capsule_type} context capsule",
            metadata={
                "capsule_type": capsule.capsule_type,
                "plan_node_id": str(capsule.plan_node_id),
                "source_refs": capsule.source_refs or [],
            },
        )
        for capsule in capsules
    ]
    artifacts.extend(
        ArtifactReference(
            artifact_id=f"external-artifact:{artifact.id}",
            artifact_type=artifact.artifact_type,
            uri=(artifact.external_url or f"postgres://external_artifacts/{artifact.id}"),
            title=(artifact.external_payload or {}).get("subject"),
            metadata={
                "system_name": artifact.system_name,
                "external_id": artifact.external_id,
                "project_record_id": str(artifact.project_id),
                "node_identity_id": (
                    str(artifact.node_identity_id)
                    if artifact.node_identity_id is not None
                    else None
                ),
            },
        )
        for artifact in external_artifacts
    )
    return artifacts
