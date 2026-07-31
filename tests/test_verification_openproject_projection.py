from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_core.agent_platform.adapters.openproject import (
    ManagedWorkPackageGateway,
)
from agent_core.agent_platform.agents.base import (
    AgentNextAction,
    AgentRunStatus,
    ArtifactReference,
)
from agent_core.agent_platform.agents.verification import (
    VerificationAgentRequest,
    VerificationAgentResult,
    VerificationOverrideCommand,
    VerificationVerdict,
)
from agent_core.agent_platform.agents.verification.contracts import (
    AcceptanceCoverageAssessment,
    AcceptanceCriterionAssessment,
    AcceptanceCriterionOutcome,
    RegressionRiskLevel,
    VerificationEvidenceSummary,
    VerificationFinding,
)
from agent_core.agent_platform.config import AgentConfig
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentOrchestrationResult,
    AgentRouteDecision,
    InMemoryAgentFlowStore,
    PersistedAgentResult,
)
from agent_core.agent_platform.runtime import AgentDependencyContainer
from agent_core.application.openproject_mapping import (
    OpenProjectResourceCatalog,
)
from agent_core.domain.coding import CodingAttemptResult, RollbackPlan
from agent_core.domain.enums import CodingAttemptStatus
from agent_core.schemas import AcceptanceCriterionSpec
from agent_core.services.agent_platform_service import (
    create_agent_platform_service,
)
from agent_core.services.verification_projection_service import (
    VerificationOpenProjectProjectionService,
    VerificationProjectionError,
)


class FakeWorkPackageGateway:
    def __init__(self) -> None:
        self.catalog_calls = 0
        self.comments: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.events: list[str] = []

    async def load_resource_catalog(self) -> OpenProjectResourceCatalog:
        self.catalog_calls += 1
        return OpenProjectResourceCatalog(
            status_hrefs={
                "Verified": "/api/v3/statuses/8",
                "Changes required": "/api/v3/statuses/9",
                "Blocked": "/api/v3/statuses/10",
                "Done": "/api/v3/statuses/11",
                "Closed": "/api/v3/statuses/12",
            }
        )

    async def add_comment(self, **kwargs):
        self.events.append("comment")
        self.comments.append(kwargs)
        return {"id": len(self.comments)}

    async def create_or_update_work_package(self, **kwargs):
        self.events.append("update")
        self.updates.append(kwargs)
        return {"id": kwargs["payload"]["id"]}


def _request(
    *,
    work_package_ids: tuple[str, ...] = ("44",),
) -> VerificationAgentRequest:
    project_record_id = uuid4()
    node_identity_id = uuid4()
    return VerificationAgentRequest(
        project_id="demo",
        task_id="task.verify-projection",
        objective="Verify projection behavior.",
        input_artifacts=[
            ArtifactReference(
                artifact_id=f"external-artifact:{index}",
                artifact_type="work_package",
                uri=f"https://openproject.test/work_packages/{work_package_id}",
                metadata={
                    "system_name": "openproject",
                    "external_id": work_package_id,
                    "project_record_id": str(project_record_id),
                    "node_identity_id": str(node_identity_id),
                },
            )
            for index, work_package_id in enumerate(work_package_ids)
        ],
        metadata={
            "transition_context": {
                "project_record_id": str(project_record_id),
                "plan_node_identity_id": str(node_identity_id),
                "openproject_project_id": "12",
            }
        },
        acceptance_criteria=[
            AcceptanceCriterionSpec(
                key="ac.projection",
                statement="Project verification evidence.",
                verification_method="unit_test",
            )
        ],
    )


def _execution(
    request: VerificationAgentRequest,
    *,
    projection_enabled: bool = True,
    human_override_enabled: bool = False,
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        workflow_id="verification-projection-workflow",
        agent_type="verification",
        request=request,
        config=AgentConfig(
            agent_type="verification",
            checkpoint_namespace="verification",
            settings={
                "openproject_projection_enabled": projection_enabled,
                "human_override_enabled": human_override_enabled,
                "human_override_allowed_verdicts": ["changes_requested"],
            },
        ),
        correlation_id="verification-projection-correlation",
    )


def _result(
    request: VerificationAgentRequest,
    verdict: VerificationVerdict,
) -> VerificationAgentResult:
    passed = verdict in {
        VerificationVerdict.PASSED,
        VerificationVerdict.PASSED_WITH_WARNINGS,
    }
    criterion = AcceptanceCriterionAssessment(
        criterion_key="ac.projection",
        statement="Project verification evidence.",
        verification_method="unit_test",
        outcome=(
            AcceptanceCriterionOutcome.SATISFIED
            if passed
            else AcceptanceCriterionOutcome.UNSATISFIED
        ),
        rationale="Evidence was independently assessed.",
        evidence_sources=["pytest"],
    )
    return VerificationAgentResult(
        execution_id=request.execution_id,
        project_id=request.project_id,
        task_id=request.task_id,
        status=AgentRunStatus.SUCCEEDED if passed else AgentRunStatus.FAILED,
        verdict=verdict,
        summary=f"Verification concluded with {verdict.value}.",
        next_action=(
            AgentNextAction.COMPLETE if passed else AgentNextAction.RUN_CODING
        ),
        acceptance_coverage=AcceptanceCoverageAssessment(
            criteria=[criterion],
            total_count=1,
            satisfied_count=1 if passed else 0,
            unsatisfied_count=0 if passed else 1,
            mandatory_criteria_satisfied=passed,
        ),
        evidence_summary=VerificationEvidenceSummary(
            diff_present=True,
            changed_line_count=4,
            changed_files=["src/feature.py"],
            quality_command_count=2,
            test_command_count=1,
            acceptance_total_count=1,
            acceptance_satisfied_count=1 if passed else 0,
            regression_risk=RegressionRiskLevel.LOW,
            finding_counts={} if passed else {"error": 1},
        ),
        findings=(
            []
            if passed
            else [
                VerificationFinding(
                    severity="error",
                    code="acceptance_criterion_unmet",
                    message="The criterion was not satisfied.",
                    acceptance_criterion_key="ac.projection",
                )
            ]
        ),
    )


def _outcome(result: VerificationAgentResult) -> AgentOrchestrationResult:
    return AgentOrchestrationResult(
        result=result,
        persisted=PersistedAgentResult(result=result),
        route=AgentRouteDecision(
            next_action=result.next_action,
            next_agent_type=(
                "coding" if result.next_action == AgentNextAction.RUN_CODING else None
            ),
            requires_approval=False,
            escalate=result.verdict == VerificationVerdict.BLOCKED,
            reason="Verification routing.",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "expected_status_href"),
    [
        (VerificationVerdict.PASSED, "/api/v3/statuses/8"),
        (VerificationVerdict.PASSED_WITH_WARNINGS, "/api/v3/statuses/8"),
        (VerificationVerdict.CHANGES_REQUESTED, "/api/v3/statuses/9"),
        (VerificationVerdict.BLOCKED, "/api/v3/statuses/10"),
    ],
)
async def test_verification_projection_maps_verdict_and_evidence_idempotently(
    verdict: VerificationVerdict,
    expected_status_href: str,
):
    gateway = FakeWorkPackageGateway()
    projector = VerificationOpenProjectProjectionService(gateway)
    request = _request()
    execution = _execution(request)
    outcome = _outcome(_result(request, verdict))

    first = await projector.project_execution(execution, outcome)
    second = await projector.project_execution(execution, outcome)

    assert first.projected is True
    assert first.operation_keys == second.operation_keys
    assert first.target is not None
    assert first.target.work_package_id == "44"
    assert first.target.openproject_project_id == "12"
    assert isinstance(first.target.local_project_id, UUID)
    assert gateway.events == ["comment", "update", "comment", "update"]
    assert gateway.comments[0]["external_idempotency_key"].endswith(":evidence")
    assert f"`{verdict.value}`" in gateway.comments[0]["markdown"]
    expected_satisfied = 1 if verdict in {
        VerificationVerdict.PASSED,
        VerificationVerdict.PASSED_WITH_WARNINGS,
    } else 0
    assert (
        f"Acceptance criteria: {expected_satisfied}/1 satisfied"
        in gateway.comments[0]["markdown"]
    )
    assert gateway.updates[0]["external_idempotency_key"].endswith(":status")
    assert gateway.updates[0]["payload"] == {
        "id": "44",
        "_links": {
            "status": {
                "href": expected_status_href,
                "title": (
                    "Verified"
                    if verdict
                    in {
                        VerificationVerdict.PASSED,
                        VerificationVerdict.PASSED_WITH_WARNINGS,
                    }
                    else (
                        "Changes required"
                        if verdict == VerificationVerdict.CHANGES_REQUESTED
                        else "Blocked"
                    )
                ),
            }
        },
    }


@pytest.mark.asyncio
async def test_verification_projection_uses_configured_status_name():
    gateway = FakeWorkPackageGateway()
    projector = VerificationOpenProjectProjectionService(gateway)
    request = _request()
    execution = _execution(request)
    execution = execution.model_copy(
        update={
            "config": execution.config.model_copy(
                update={
                    "settings": {
                        **execution.config.settings,
                        "openproject_verified_status_name": "Closed",
                    }
                }
            )
        }
    )

    await projector.project_execution(
        execution,
        _outcome(_result(request, VerificationVerdict.PASSED)),
    )

    assert gateway.updates[0]["payload"]["_links"]["status"] == {
        "href": "/api/v3/statuses/12",
        "title": "Closed",
    }


@pytest.mark.asyncio
async def test_verification_projection_skips_disabled_or_unmapped_requests():
    gateway = FakeWorkPackageGateway()
    projector = VerificationOpenProjectProjectionService(gateway)
    unmapped = _request(work_package_ids=())

    disabled = await projector.project_execution(
        _execution(unmapped, projection_enabled=False),
        _outcome(_result(unmapped, VerificationVerdict.PASSED)),
    )
    missing = await projector.project_execution(
        _execution(unmapped),
        _outcome(_result(unmapped, VerificationVerdict.PASSED)),
    )

    assert disabled.projected is False
    assert "disabled" in disabled.reason
    assert missing.projected is False
    assert "mapping" in missing.reason
    assert gateway.catalog_calls == 0
    assert gateway.comments == []
    assert gateway.updates == []


@pytest.mark.asyncio
async def test_verification_projection_rejects_ambiguous_work_package_targets():
    gateway = FakeWorkPackageGateway()
    projector = VerificationOpenProjectProjectionService(gateway)
    request = _request(work_package_ids=("44", "45"))

    with pytest.raises(VerificationProjectionError, match="multiple"):
        await projector.project_execution(
            _execution(request),
            _outcome(_result(request, VerificationVerdict.PASSED)),
        )


def _override_coding_result() -> CodingAttemptResult:
    return CodingAttemptResult(
        task_key="task.verify-projection",
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


@pytest.mark.asyncio
async def test_agent_flow_projects_verification_and_override_history():
    gateway = FakeWorkPackageGateway()
    store = InMemoryAgentFlowStore()
    service = create_agent_platform_service(
        AgentDependencyContainer(work_package_gateway=gateway),
        flow_store=store,
    )
    request = _request()
    request = request.model_copy(
        update={
            "coding_result": _override_coding_result(),
            "repository_diff": "+unrelated implementation detail\n",
        }
    )

    waiting = await service.start_flow(
        _execution(
            request,
            human_override_enabled=True,
        )
    )
    original_payload = waiting.steps[-1].result_payload.copy()

    completed = await service.override_verification_flow(
        flow_id=waiting.flow_id,
        expected_version=waiting.version,
        command=VerificationOverrideCommand(
            actor="reviewer@example.test",
            reason="Approved through controlled change management.",
            override_reference="change-control-418",
        ),
    )

    assert completed.overrides[0].override_reference == "change-control-418"
    assert completed.steps[-1].result_payload == original_payload
    assert gateway.events == ["comment", "update", "comment", "update"]
    assert "changes_requested" in gateway.comments[0]["markdown"]
    assert "reviewer@example.test" in gateway.comments[1]["markdown"]
    assert "change-control-418" in gateway.comments[1]["markdown"]
    assert "does not alter the original" in gateway.comments[1]["markdown"]
    assert gateway.updates[1]["payload"]["_links"]["status"] == {
        "href": "/api/v3/statuses/11",
        "title": "Done",
    }
    assert gateway.comments[1]["external_idempotency_key"].startswith(
        "openproject:verification-override:"
    )


class ClosableFakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def load_resource_catalog(self):
        return OpenProjectResourceCatalog()

    async def add_comment(self, **kwargs):
        return kwargs

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_managed_work_package_gateway_closes_each_concrete_client():
    clients: list[ClosableFakeClient] = []

    def factory() -> ClosableFakeClient:
        client = ClosableFakeClient()
        clients.append(client)
        return client

    gateway = ManagedWorkPackageGateway(factory)
    await gateway.load_resource_catalog()
    await gateway.add_comment(
        work_package_id="44",
        external_idempotency_key="comment-key",
        markdown="Evidence",
    )

    assert len(clients) == 2
    assert all(client.closed for client in clients)
