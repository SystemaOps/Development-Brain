from __future__ import annotations

from uuid import uuid4

from agent_core.agent_platform.agents.base.contracts import (
    AgentNextAction,
    ArtifactReference,
)
from agent_core.agent_platform.agents.base.errors import AgentConfigurationError
from agent_core.agent_platform.agents.coding.state import (
    CodingAgentRequest,
    CodingAgentResult,
)
from agent_core.agent_platform.agents.planning.state import (
    PlanningAgentRequest,
    PlanningAgentResult,
)
from agent_core.agent_platform.agents.verification.state import (
    VerificationAgentRequest,
    VerificationAgentResult,
)
from agent_core.agent_platform.config.models import AgentPlatformConfig
from agent_core.agent_platform.orchestration.contracts import AgentExecutionRequest
from agent_core.agent_platform.orchestration.orchestrator import (
    AgentOrchestrationResult,
)
from agent_core.agent_platform.orchestration.routing import AgentRouteDecision
from agent_core.agent_platform.orchestration.transition_context import (
    AgentTaskTransitionContext,
    AgentTransitionContextStore,
)
from agent_core.domain.coding import CodingAttemptResult
from agent_core.domain.enums import PlanNodeKind


class ApplicationAgentTransitionResolver:
    """Builds specialized handoff requests from durable task transition context."""

    def __init__(
        self,
        *,
        context_store: AgentTransitionContextStore,
        config: AgentPlatformConfig,
    ) -> None:
        self.context_store = context_store
        self.config = config

    async def resolve_next(
        self,
        *,
        previous_execution: AgentExecutionRequest,
        previous_outcome: AgentOrchestrationResult,
        route: AgentRouteDecision,
    ) -> AgentExecutionRequest | None:
        if route.next_action == AgentNextAction.RETRY:
            return self._retry(previous_execution, previous_outcome)

        target_agent_type = route.next_agent_type
        if target_agent_type == "planning":
            return self._planning_request(previous_execution, previous_outcome)
        if target_agent_type not in {"coding", "verification"}:
            raise AgentConfigurationError(
                f"No application transition resolver is registered for '{target_agent_type}'"
            )

        task_id = _resolve_task_id(previous_execution, previous_outcome)
        if task_id is None:
            return None
        context = await self.context_store.load_task_context(
            project_id=previous_execution.request.project_id,
            task_id=task_id,
            workflow_id=previous_execution.workflow_id,
            plan_version_id=_plan_version_id(previous_execution),
        )
        if context is None:
            return None

        if target_agent_type == "coding":
            return self._coding_request(previous_execution, previous_outcome, context)
        return self._verification_request(previous_execution, previous_outcome, context)

    def _retry(
        self,
        previous_execution: AgentExecutionRequest,
        previous_outcome: AgentOrchestrationResult,
    ) -> AgentExecutionRequest:
        metadata = dict(previous_execution.request.metadata)
        metadata.update(
            {
                "retry_of_execution_id": str(previous_execution.request.execution_id),
                "retry_of_result_id": str(previous_outcome.persisted.result_id),
            }
        )
        request = previous_execution.request.model_copy(
            deep=True,
            update={
                "execution_id": uuid4(),
                "state": previous_outcome.result.state,
                "metadata": metadata,
            },
        )
        return AgentExecutionRequest(
            workflow_id=previous_execution.workflow_id,
            agent_type=previous_execution.agent_type,
            request=request,
            config=previous_execution.config,
            correlation_id=previous_execution.correlation_id,
        )

    def _planning_request(
        self,
        previous_execution: AgentExecutionRequest,
        previous_outcome: AgentOrchestrationResult,
    ) -> AgentExecutionRequest:
        request = PlanningAgentRequest(
            project_id=previous_execution.request.project_id,
            task_id=previous_outcome.result.task_id or previous_execution.request.task_id,
            objective=f"Replan after {previous_outcome.result.agent_type}: {previous_execution.request.objective}",
            original_request=previous_execution.request.objective,
            input_artifacts=_merge_artifacts(
                previous_execution.request.input_artifacts,
                previous_outcome.result.output_artifacts,
            ),
            metadata=_transition_metadata(previous_execution, previous_outcome),
        )
        return self._execution(previous_execution, request)

    def _coding_request(
        self,
        previous_execution: AgentExecutionRequest,
        previous_outcome: AgentOrchestrationResult,
        context: AgentTaskTransitionContext,
    ) -> AgentExecutionRequest | None:
        is_rework = previous_outcome.result.agent_type == "verification"
        coding_attempt = (
            context.prepared_rework_attempt if is_rework else context.prepared_coding_attempt
        )
        if coding_attempt is None:
            return None
        if coding_attempt.task_key != context.task_id:
            raise AgentConfigurationError(
                "Prepared coding attempt task_key does not match transition task_id"
            )

        approved = context.planning_approved
        if previous_outcome.result.agent_type == "planning":
            approved = approved or not previous_execution.config.approval_required
        elif is_rework and context.latest_coding_attempt is not None:
            approved = True
        if not approved:
            return None

        metadata = _transition_metadata(previous_execution, previous_outcome)
        metadata.update(
            {
                "approval_verified": True,
                "acceptance_criteria": [
                    item.model_dump(mode="json") for item in context.acceptance_criteria
                ],
                "transition_context": context.metadata,
            }
        )
        if isinstance(previous_outcome.result, VerificationAgentResult):
            metadata["verification_findings"] = [
                finding.model_dump(mode="json") for finding in previous_outcome.result.findings
            ]

        request = CodingAgentRequest(
            project_id=previous_execution.request.project_id,
            task_id=context.task_id,
            objective=context.objective,
            input_artifacts=_merge_artifacts(
                previous_execution.request.input_artifacts,
                previous_outcome.result.output_artifacts,
                context.input_artifacts,
            ),
            metadata=metadata,
            coding_attempt=coding_attempt,
            approved=True,
        )
        return self._execution(previous_execution, request)

    def _verification_request(
        self,
        previous_execution: AgentExecutionRequest,
        previous_outcome: AgentOrchestrationResult,
        context: AgentTaskTransitionContext,
    ) -> AgentExecutionRequest | None:
        coding_result = None
        if isinstance(previous_outcome.result, CodingAgentResult):
            coding_result = previous_outcome.result.coding_result
        coding_result = coding_result or context.latest_coding_result
        if coding_result is None or not context.acceptance_criteria:
            return None
        if coding_result.task_key != context.task_id:
            raise AgentConfigurationError(
                "Coding result task_key does not match transition task_id"
            )

        request = VerificationAgentRequest(
            project_id=previous_execution.request.project_id,
            task_id=context.task_id,
            objective=f"Verify implementation of {context.objective}",
            input_artifacts=_merge_artifacts(
                previous_execution.request.input_artifacts,
                previous_outcome.result.output_artifacts,
                context.input_artifacts,
            ),
            metadata={
                **_transition_metadata(previous_execution, previous_outcome),
                "transition_context": context.metadata,
            },
            acceptance_criteria=context.acceptance_criteria,
            coding_result=coding_result,
            repository_diff=coding_result.final_diff,
            test_evidence=_test_evidence(coding_result),
        )
        return self._execution(previous_execution, request)

    def _execution(
        self,
        previous_execution: AgentExecutionRequest,
        request: PlanningAgentRequest | CodingAgentRequest | VerificationAgentRequest,
    ) -> AgentExecutionRequest:
        config = self.config.agents.get(request.agent_type)
        if config is None:
            raise AgentConfigurationError(
                f"Missing configuration for transition target '{request.agent_type}'"
            )
        return AgentExecutionRequest(
            workflow_id=previous_execution.workflow_id,
            agent_type=request.agent_type,
            request=request,
            config=config,
            correlation_id=previous_execution.correlation_id,
        )


def _resolve_task_id(
    previous_execution: AgentExecutionRequest,
    previous_outcome: AgentOrchestrationResult,
) -> str | None:
    explicit = (
        previous_outcome.result.metadata.get("next_task_id")
        or previous_execution.request.metadata.get("next_task_id")
        or previous_outcome.result.task_id
        or previous_execution.request.task_id
    )
    if explicit:
        return str(explicit)

    if isinstance(previous_outcome.result, PlanningAgentResult):
        plan = previous_outcome.result.plan
        if plan is not None:
            tasks = [node.stable_key for node in plan.nodes if node.kind == PlanNodeKind.TASK]
            if len(tasks) == 1:
                return tasks[0]
    return None


def _transition_metadata(
    previous_execution: AgentExecutionRequest,
    previous_outcome: AgentOrchestrationResult,
) -> dict:
    return {
        "transition_from_agent": previous_outcome.result.agent_type,
        "transition_from_execution_id": str(previous_execution.request.execution_id),
        "transition_from_result_id": str(previous_outcome.persisted.result_id),
    }


def _plan_version_id(previous_execution: AgentExecutionRequest) -> str | None:
    transition_context = previous_execution.request.metadata.get("transition_context")
    if not isinstance(transition_context, dict):
        return None
    value = transition_context.get("plan_version_id")
    return str(value) if value else None


def _merge_artifacts(*groups: list[ArtifactReference]) -> list[ArtifactReference]:
    merged: dict[str, ArtifactReference] = {}
    for group in groups:
        for artifact in group:
            merged[artifact.artifact_id] = artifact
    return list(merged.values())


def _test_evidence(coding_result: CodingAttemptResult) -> list[str]:
    evidence = [item.excerpt or item.title or item.uri for item in coding_result.evidence]
    for command in coding_result.command_results:
        evidence.append(
            "\n".join(
                part
                for part in [
                    f"$ {' '.join(command.command)} (exit {command.exit_code})",
                    command.stdout,
                    command.stderr,
                ]
                if part
            )
        )
    return evidence
