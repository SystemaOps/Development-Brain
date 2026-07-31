from __future__ import annotations

from pydantic import BaseModel, Field

from agent_core.agent_platform.adapters.openproject import WorkPackageGateway
from agent_core.agent_platform.agents.verification.config import (
    VerificationAgentConfig,
)
from agent_core.agent_platform.agents.verification.state import (
    VerificationAgentRequest,
    VerificationAgentResult,
)
from agent_core.agent_platform.config.models import (
    AgentConfig,
    materialize_agent_config,
)
from agent_core.agent_platform.orchestration.contracts import (
    AgentExecutionRequest,
)
from agent_core.agent_platform.orchestration.flow import AgentFlowResult
from agent_core.agent_platform.orchestration.flow_persistence import (
    AgentFlowOverrideRecord,
    AgentFlowStepRecord,
    PersistedAgentFlow,
)
from agent_core.agent_platform.orchestration.orchestrator import (
    AgentOrchestrationResult,
)
from agent_core.application.openproject_mapping import (
    OpenProjectSemanticMapper,
    OpenProjectSemanticMapping,
    OpenProjectSemanticStatus,
)
from agent_core.application.openproject_verification import (
    VerificationOpenProjectTarget,
    VerificationProjectionError,
    VerificationProjectionOperation,
    VerificationProjectionOperationType,
    build_override_projection_operations,
    build_verification_projection_operations,
    resolve_verification_openproject_target,
)


class VerificationProjectionOutcome(BaseModel):
    projected: bool
    reason: str
    target: VerificationOpenProjectTarget | None = None
    operation_keys: list[str] = Field(default_factory=list)


class VerificationOpenProjectProjectionService:
    """Projects immutable Verification results through an injected work-package port."""

    def __init__(self, gateway: WorkPackageGateway | None) -> None:
        self.gateway = gateway

    async def project_execution(
        self,
        execution: AgentExecutionRequest,
        outcome: AgentOrchestrationResult,
    ) -> VerificationProjectionOutcome:
        if not isinstance(outcome.result, VerificationAgentResult):
            return _skipped("The execution did not produce a Verification Agent result.")
        config = VerificationAgentConfig.model_validate(
            materialize_agent_config(execution.config)
        )
        if not config.openproject_projection_enabled:
            return _skipped("OpenProject verification projection is disabled.")
        if self.gateway is None:
            return _skipped("No OpenProject work-package gateway is configured.")

        request = VerificationAgentRequest.model_validate(execution.request)
        target = resolve_verification_openproject_target(request)
        if target is None:
            return _skipped("No OpenProject work-package mapping was supplied.")

        operations = build_verification_projection_operations(
            request=request,
            result=outcome.result,
        )
        await self._execute(target, operations, config=config)
        return VerificationProjectionOutcome(
            projected=True,
            reason="Verification status and evidence projected to OpenProject.",
            target=target,
            operation_keys=[operation.idempotency_key for operation in operations],
        )

    async def project_flow(
        self,
        result: AgentFlowResult,
    ) -> list[VerificationProjectionOutcome]:
        outcomes: list[VerificationProjectionOutcome] = []
        for step in result.steps:
            if step.execution.agent_type == "verification":
                outcomes.append(
                    await self.project_execution(step.execution, step.outcome)
                )
        return outcomes

    async def project_override(
        self,
        *,
        flow: PersistedAgentFlow,
        source: AgentFlowStepRecord,
        result: VerificationAgentResult,
        override: AgentFlowOverrideRecord,
    ) -> VerificationProjectionOutcome:
        config = VerificationAgentConfig.model_validate(
            materialize_agent_config(
                AgentConfig.model_validate(source.request_payload.get("config"))
            )
        )
        if not config.openproject_projection_enabled:
            return _skipped("OpenProject verification projection is disabled.")
        if self.gateway is None:
            return _skipped("No OpenProject work-package gateway is configured.")

        request = VerificationAgentRequest.model_validate(
            source.request_payload.get("request")
        )
        target = resolve_verification_openproject_target(request)
        if target is None:
            return _skipped("No OpenProject work-package mapping was supplied.")

        operations = build_override_projection_operations(
            workflow_id=flow.workflow_id,
            request=request,
            result=result,
            override=override,
        )
        await self._execute(target, operations, config=config)
        return VerificationProjectionOutcome(
            projected=True,
            reason="Verification override status and audit projected to OpenProject.",
            target=target,
            operation_keys=[operation.idempotency_key for operation in operations],
        )

    async def _execute(
        self,
        target: VerificationOpenProjectTarget,
        operations: list[VerificationProjectionOperation],
        *,
        config: VerificationAgentConfig,
    ) -> None:
        if self.gateway is None:
            raise AssertionError("OpenProject gateway disappeared during projection")
        catalog = await self.gateway.load_resource_catalog()
        mapper = OpenProjectSemanticMapper(
            catalog=catalog,
            mapping=_semantic_mapping(config),
        )

        for operation in operations:
            if operation.markdown is not None:
                await self.gateway.add_comment(
                    work_package_id=target.work_package_id,
                    external_idempotency_key=operation.idempotency_key,
                    markdown=operation.markdown,
                    local_project_id=target.local_project_id,
                    node_identity_id=target.node_identity_id,
                )
                continue
            if operation.semantic_status is None:
                raise VerificationProjectionError(
                    f"Projection operation {operation.operation_type} has no payload"
                )
            status_link = mapper.status_link_for_semantic_status(
                operation.semantic_status
            )
            await self.gateway.create_or_update_work_package(
                project_id=target.openproject_project_id,
                external_idempotency_key=operation.idempotency_key,
                payload={
                    "id": target.work_package_id,
                    "_links": {
                        "status": status_link.as_hal_link(),
                    },
                },
                local_project_id=target.local_project_id,
                node_identity_id=target.node_identity_id,
            )


def _skipped(reason: str) -> VerificationProjectionOutcome:
    return VerificationProjectionOutcome(projected=False, reason=reason)


def _semantic_mapping(
    config: VerificationAgentConfig,
) -> OpenProjectSemanticMapping:
    default = OpenProjectSemanticMapping()
    status_names = dict(default.status_names_by_semantic_status)
    status_names.update(
        {
            OpenProjectSemanticStatus.VERIFIED: config.openproject_verified_status_name,
            OpenProjectSemanticStatus.CHANGES_REQUIRED: (
                config.openproject_changes_required_status_name
            ),
            OpenProjectSemanticStatus.BLOCKED: config.openproject_blocked_status_name,
            OpenProjectSemanticStatus.DONE: config.openproject_override_status_name,
        }
    )
    return OpenProjectSemanticMapping(
        status_names_by_semantic_status=status_names,
    )


__all__ = [
    "VerificationOpenProjectProjectionService",
    "VerificationOpenProjectTarget",
    "VerificationProjectionError",
    "VerificationProjectionOperation",
    "VerificationProjectionOperationType",
    "VerificationProjectionOutcome",
]
