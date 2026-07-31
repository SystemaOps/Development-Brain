from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agent_core.agent_platform.agents.verification.contracts import (
    VerificationVerdict,
)
from agent_core.agent_platform.agents.verification.state import (
    VerificationAgentRequest,
    VerificationAgentResult,
)
from agent_core.agent_platform.orchestration.flow_persistence import (
    AgentFlowOverrideRecord,
)
from agent_core.application.openproject_mapping import (
    OpenProjectSemanticStatus,
)


class VerificationProjectionOperationType(StrEnum):
    EVIDENCE_COMMENT = "evidence_comment"
    STATUS_UPDATE = "status_update"
    OVERRIDE_AUDIT_COMMENT = "override_audit_comment"
    OVERRIDE_STATUS_UPDATE = "override_status_update"


class VerificationOpenProjectTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_key: str
    task_key: str
    work_package_id: str
    openproject_project_id: str
    local_project_id: UUID | None = None
    node_identity_id: UUID | None = None


class VerificationProjectionOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_type: VerificationProjectionOperationType
    idempotency_key: str
    markdown: str | None = None
    semantic_status: OpenProjectSemanticStatus | None = None


class VerificationProjectionError(RuntimeError):
    pass


def resolve_verification_openproject_target(
    request: VerificationAgentRequest,
) -> VerificationOpenProjectTarget | None:
    metadata = request.metadata
    transition = metadata.get("transition_context")
    transition_metadata = transition if isinstance(transition, dict) else {}

    explicit_work_package_id = _first_text(
        metadata,
        transition_metadata,
        keys=(
            "openproject_work_package_id",
            "external_work_package_id",
            "work_package_id",
        ),
    )
    artifacts = [
        artifact
        for artifact in request.input_artifacts
        if artifact.artifact_type == "work_package"
        and artifact.metadata.get("system_name") == "openproject"
        and artifact.metadata.get("external_id")
    ]
    artifact_ids = {str(item.metadata["external_id"]) for item in artifacts}
    if explicit_work_package_id is None:
        if not artifact_ids:
            return None
        if len(artifact_ids) > 1:
            raise VerificationProjectionError(
                "Verification request contains multiple OpenProject work-package mappings."
            )
        work_package_id = next(iter(artifact_ids))
    else:
        work_package_id = explicit_work_package_id

    matching_artifact = next(
        (
            artifact
            for artifact in artifacts
            if str(artifact.metadata.get("external_id")) == work_package_id
        ),
        None,
    )
    local_project_id = _first_uuid(
        metadata,
        transition_metadata,
        matching_artifact.metadata if matching_artifact is not None else {},
        keys=("project_record_id", "local_project_id"),
    )
    node_identity_id = _first_uuid(
        metadata,
        transition_metadata,
        matching_artifact.metadata if matching_artifact is not None else {},
        keys=("plan_node_identity_id", "node_identity_id"),
    )
    openproject_project_id = _first_text(
        metadata,
        transition_metadata,
        keys=(
            "openproject_project_id",
            "openproject_project_identifier",
            "external_project_id",
        ),
    )
    return VerificationOpenProjectTarget(
        project_key=request.project_id,
        task_key=request.task_id or "unscoped-task",
        work_package_id=work_package_id,
        openproject_project_id=openproject_project_id or request.project_id,
        local_project_id=local_project_id,
        node_identity_id=node_identity_id,
    )


def build_verification_projection_operations(
    *,
    request: VerificationAgentRequest,
    result: VerificationAgentResult,
) -> list[VerificationProjectionOperation]:
    key_prefix = f"openproject:verification:{result.execution_id}"
    return [
        VerificationProjectionOperation(
            operation_type=VerificationProjectionOperationType.EVIDENCE_COMMENT,
            idempotency_key=f"{key_prefix}:evidence",
            markdown=_verification_markdown(request=request, result=result),
        ),
        VerificationProjectionOperation(
            operation_type=VerificationProjectionOperationType.STATUS_UPDATE,
            idempotency_key=f"{key_prefix}:status",
            semantic_status=_semantic_status(result.verdict),
        ),
    ]


def build_override_projection_operations(
    *,
    workflow_id: str,
    request: VerificationAgentRequest,
    result: VerificationAgentResult,
    override: AgentFlowOverrideRecord,
) -> list[VerificationProjectionOperation]:
    key_prefix = f"openproject:verification-override:{override.override_id}"
    return [
        VerificationProjectionOperation(
            operation_type=VerificationProjectionOperationType.OVERRIDE_AUDIT_COMMENT,
            idempotency_key=f"{key_prefix}:audit",
            markdown=_override_markdown(
                workflow_id=workflow_id,
                request=request,
                result=result,
                override=override,
            ),
        ),
        VerificationProjectionOperation(
            operation_type=VerificationProjectionOperationType.OVERRIDE_STATUS_UPDATE,
            idempotency_key=f"{key_prefix}:status",
            semantic_status=OpenProjectSemanticStatus.DONE,
        ),
    ]


def _semantic_status(verdict: VerificationVerdict) -> OpenProjectSemanticStatus:
    return {
        VerificationVerdict.PASSED: OpenProjectSemanticStatus.VERIFIED,
        VerificationVerdict.PASSED_WITH_WARNINGS: OpenProjectSemanticStatus.VERIFIED,
        VerificationVerdict.CHANGES_REQUESTED: OpenProjectSemanticStatus.CHANGES_REQUIRED,
        VerificationVerdict.BLOCKED: OpenProjectSemanticStatus.BLOCKED,
    }[verdict]


def _verification_markdown(
    *,
    request: VerificationAgentRequest,
    result: VerificationAgentResult,
) -> str:
    summary = result.evidence_summary
    lines = [
        f"## Verification result: `{result.verdict.value}`",
        f"- Task: `{request.task_id or 'not specified'}`",
        f"- Execution: `{result.execution_id}`",
        f"- Summary: {result.summary}",
        (
            "- Acceptance criteria: "
            f"{summary.acceptance_satisfied_count}/{summary.acceptance_total_count} satisfied"
        ),
        (
            "- Checks: "
            f"{summary.test_command_count} test, "
            f"{summary.quality_command_count} total quality commands, "
            f"{summary.external_test_evidence_count} external evidence items"
        ),
        f"- Regression risk: `{summary.regression_risk.value}`",
        f"- Security issues: {summary.security_issue_count}",
        f"- Changed files: {len(summary.changed_files)}",
    ]
    if result.acceptance_coverage.criteria:
        lines.extend(["", "### Acceptance criteria"])
        lines.extend(
            (
                f"- `{criterion.criterion_key}`: `{criterion.outcome.value}`"
                f" - {criterion.rationale}"
            )
            for criterion in result.acceptance_coverage.criteria
        )
    if result.findings:
        lines.extend(["", "### Findings"])
        lines.extend(
            (
                f"- **{finding.severity}** `{finding.code}`"
                f"{_criterion_suffix(finding.acceptance_criterion_key)}: {finding.message}"
            )
            for finding in result.findings
        )
    if result.evidence:
        lines.extend(["", "### Evidence"])
        lines.extend(
            f"- [{item.title or item.evidence_type}]({item.uri})"
            for item in result.evidence
        )
    return "\n".join(lines)


def _override_markdown(
    *,
    workflow_id: str,
    request: VerificationAgentRequest,
    result: VerificationAgentResult,
    override: AgentFlowOverrideRecord,
) -> str:
    lines = [
        "## Verification completion override",
        f"- Task: `{request.task_id or 'not specified'}`",
        f"- Workflow: `{workflow_id}`",
        f"- Original verification verdict: `{result.verdict.value}`",
        f"- Original verification execution: `{result.execution_id}`",
        f"- Override actor: {override.actor}",
        f"- Override reference: `{override.override_reference}`",
        f"- Recorded at: `{override.recorded_at.isoformat()}`",
        f"- Reason: {override.reason}",
    ]
    if override.finding_codes:
        lines.append(
            "- Original finding codes: "
            + ", ".join(f"`{code}`" for code in override.finding_codes)
        )
    if override.affected_item_keys:
        lines.append(
            "- Affected acceptance criteria: "
            + ", ".join(f"`{key}`" for key in override.affected_item_keys)
        )
    lines.extend(
        [
            "",
            (
                "This records an explicit human completion decision. "
                "It does not alter the original Verification Agent result."
            ),
        ]
    )
    return "\n".join(lines)


def _criterion_suffix(criterion_key: str | None) -> str:
    return f" ({criterion_key})" if criterion_key else ""


def _first_text(
    *sources: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _first_uuid(
    *sources: dict[str, Any],
    keys: tuple[str, ...],
) -> UUID | None:
    value = _first_text(*sources, keys=keys)
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise VerificationProjectionError(
            f"OpenProject projection metadata contains an invalid UUID: {value}"
        ) from exc


__all__ = [
    "VerificationOpenProjectTarget",
    "VerificationProjectionError",
    "VerificationProjectionOperation",
    "VerificationProjectionOperationType",
    "build_override_projection_operations",
    "build_verification_projection_operations",
    "resolve_verification_openproject_target",
]
