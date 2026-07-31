from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentRunStatus,
)
from agent_core.agent_platform.agents.verification import (
    VerificationAgentConfig,
    VerificationAgentRequest,
    VerificationOverrideCommand,
    VerificationOverridePolicyError,
    VerificationOverrideType,
    VerificationVerdict,
    assess_verification_override,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowOverrideRecord,
    AgentFlowPersistenceError,
    AgentFlowStatus,
    AgentFlowVersionConflictError,
    InMemoryAgentFlowStore,
)
from agent_core.agent_platform.runtime import AgentDependencyContainer
from agent_core.domain.coding import CodingAttemptResult, RollbackPlan
from agent_core.domain.enums import CodingAttemptStatus
from agent_core.schemas import AcceptanceCriterionSpec
from agent_core.services.agent_platform_service import (
    create_agent_platform_service,
)


def _coding_result() -> CodingAttemptResult:
    return CodingAttemptResult(
        task_key="task.verification-override",
        repository_key="demo",
        attempt_number=1,
        status=CodingAttemptStatus.SUCCEEDED,
        changed_files=["src/feature.py"],
        final_diff="+unrelated implementation detail\n",
        rollback_plan=RollbackPlan(
            available=True,
            strategy="reverse_diff",
            changed_files=["src/feature.py"],
        ),
    )


def _execution(
    *,
    human_override_enabled: bool,
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        workflow_id="verification-override-workflow",
        agent_type="verification",
        request=VerificationAgentRequest(
            project_id="demo",
            task_id="task.verification-override",
            objective="Verify the required audit behavior.",
            acceptance_criteria=[
                AcceptanceCriterionSpec(
                    key="ac.override-audit",
                    statement="Verification override creates a durable audit record.",
                    verification_method="integration_test",
                )
            ],
            coding_result=_coding_result(),
        ),
        config=AgentConfig(
            agent_type="verification",
            checkpoint_namespace="verification",
            settings={
                "human_override_enabled": human_override_enabled,
                "human_override_allowed_verdicts": ["changes_requested"],
            },
        ),
        correlation_id="verification-override-correlation",
    )


def _command() -> VerificationOverrideCommand:
    return VerificationOverrideCommand(
        actor="reviewer@example.test",
        reason="The unmet criterion is accepted for this controlled release.",
        override_reference="change-control-417",
        metadata={"ticket": "CC-417"},
    )


class FailingOnceOverrideProjector:
    def __init__(self) -> None:
        self.override_ids = []

    async def project_flow(self, result):
        return []

    async def project_override(self, **kwargs):
        self.override_ids.append(kwargs["override"].override_id)
        if len(self.override_ids) == 1:
            raise RuntimeError("temporary OpenProject failure")


def test_override_contract_and_configuration_reject_unsafe_values():
    with pytest.raises(ValidationError):
        VerificationOverrideCommand(
            actor="reviewer@example.test",
            reason=" ",
            override_reference="change-control-417",
        )

    with pytest.raises(ValidationError, match="changes_requested or blocked"):
        VerificationAgentConfig(
            agent_type="verification",
            checkpoint_namespace="verification",
            human_override_enabled=True,
            human_override_allowed_verdicts=[VerificationVerdict.PASSED],
        )

    with pytest.raises(ValidationError, match="cannot be empty"):
        VerificationAgentConfig(
            agent_type="verification",
            checkpoint_namespace="verification",
            human_override_enabled=True,
            human_override_allowed_verdicts=[],
        )


@pytest.mark.asyncio
async def test_verification_override_completes_flow_and_preserves_original_result():
    store = InMemoryAgentFlowStore()
    service = create_agent_platform_service(
        AgentDependencyContainer(),
        flow_store=store,
    )

    waiting = await service.start_flow(_execution(human_override_enabled=True))

    assert waiting.status == AgentFlowStatus.WAITING_FOR_APPROVAL
    assert waiting.version == 2
    assert waiting.pending_route is not None
    assert waiting.pending_route.requires_approval is True
    assert waiting.steps[-1].result_payload["verdict"] == (
        VerificationVerdict.CHANGES_REQUESTED.value
    )
    assert waiting.steps[-1].result_payload["status"] == AgentRunStatus.FAILED.value
    assert waiting.steps[-1].result_payload["next_action"] == (
        AgentNextAction.REQUEST_APPROVAL.value
    )
    assert waiting.steps[-1].result_payload["human_override_eligible"] is True

    with pytest.raises(AgentFlowPersistenceError, match="source identity"):
        await store.complete_override(
            flow_id=waiting.flow_id,
            expected_version=waiting.version,
            override=AgentFlowOverrideRecord(
                override_type=VerificationOverrideType.COMPLETION.value,
                source_step_sequence=waiting.steps[-1].sequence,
                source_agent_type="verification",
                source_execution_id=waiting.steps[-1].execution_id,
                source_result_id=uuid4(),
                original_status=AgentRunStatus.FAILED,
                original_next_action=AgentNextAction.REQUEST_APPROVAL,
                original_outcome=VerificationVerdict.CHANGES_REQUESTED.value,
                actor="reviewer@example.test",
                reason="Invalid source identity test.",
                override_reference="invalid-source",
            ),
        )

    completed = await service.override_verification_flow(
        flow_id=waiting.flow_id,
        expected_version=waiting.version,
        command=_command(),
    )

    assert completed.status == AgentFlowStatus.COMPLETED
    assert completed.version == 3
    assert completed.pending_route is None
    assert completed.step_count == 1
    assert completed.steps == waiting.steps
    assert len(completed.overrides) == 1

    audit = completed.overrides[0]
    assert audit.override_type == VerificationOverrideType.COMPLETION.value
    assert audit.source_step_sequence == waiting.steps[-1].sequence
    assert audit.source_execution_id == waiting.steps[-1].execution_id
    assert audit.source_result_id == waiting.steps[-1].result_id
    assert audit.original_status == AgentRunStatus.FAILED
    assert audit.original_next_action == AgentNextAction.REQUEST_APPROVAL
    assert audit.original_outcome == VerificationVerdict.CHANGES_REQUESTED.value
    assert audit.finding_codes == ["acceptance_criterion_unmet"]
    assert audit.affected_item_keys == ["ac.override-audit"]
    assert audit.actor == "reviewer@example.test"
    assert audit.reason == _command().reason
    assert audit.override_reference == "change-control-417"
    assert audit.metadata == {"ticket": "CC-417"}

    reloaded = await service.get_flow(completed.flow_id)
    assert reloaded == completed
    with pytest.raises(AgentFlowVersionConflictError):
        await service.override_verification_flow(
            flow_id=waiting.flow_id,
            expected_version=waiting.version,
            command=_command(),
        )


@pytest.mark.asyncio
async def test_disabled_override_policy_keeps_normal_rework_route():
    service = create_agent_platform_service(AgentDependencyContainer())
    result = await service.execute_flow(_execution(human_override_enabled=False))

    assert result.status == AgentFlowStatus.TRANSITION_PENDING
    assert result.final_outcome.result.next_action == AgentNextAction.RUN_CODING
    assert result.final_outcome.result.human_override_eligible is False

    with pytest.raises(VerificationOverridePolicyError, match="disabled"):
        assess_verification_override(
            config=VerificationAgentConfig(
                agent_type="verification",
                checkpoint_namespace="verification",
            ),
            result=result.final_outcome.result,
        )


@pytest.mark.asyncio
async def test_verification_override_keeps_projection_identity_across_retry():
    store = InMemoryAgentFlowStore()
    projector = FailingOnceOverrideProjector()
    service = create_agent_platform_service(
        AgentDependencyContainer(),
        flow_store=store,
        verification_projection_service=projector,
    )
    waiting = await service.start_flow(_execution(human_override_enabled=True))

    with pytest.raises(RuntimeError, match="temporary OpenProject failure"):
        await service.override_verification_flow(
            flow_id=waiting.flow_id,
            expected_version=waiting.version,
            command=_command(),
        )

    unchanged = await service.get_flow(waiting.flow_id)
    assert unchanged.status == AgentFlowStatus.WAITING_FOR_APPROVAL
    assert unchanged.version == waiting.version
    completed = await service.override_verification_flow(
        flow_id=waiting.flow_id,
        expected_version=waiting.version,
        command=_command(),
    )

    assert completed.status == AgentFlowStatus.COMPLETED
    assert projector.override_ids[0] == projector.override_ids[1]
    assert completed.overrides[0].override_id == projector.override_ids[0]
