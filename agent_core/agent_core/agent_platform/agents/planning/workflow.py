from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.base.contracts import (
    AgentError,
    AgentErrorCategory,
    AgentNextAction,
    AgentRunStatus,
    ArtifactReference,
)
from agent_core.agent_platform.agents.base.workflow import (
    AgentWorkflowRuntime,
    persist_workflow_state,
)
from agent_core.agent_platform.agents.planning.config import (
    PlanningAgentConfig,
)
from agent_core.agent_platform.agents.planning.state import (
    PlanningAgentRequest,
    PlanningAgentResult,
    PlanningAgentState,
)
from agent_core.agent_platform.runtime.dependency_container import (
    AgentDependencyContainer,
)
from agent_core.agent_platform.runtime.execution_context import (
    AgentExecutionContext,
)
from agent_core.domain.evidence import EvidenceRef
from agent_core.schemas import ProjectPlanSpec
from agent_core.skills.base import SkillContext
from agent_core.skills.plan_validation import (
    PlanValidationInput,
    PlanValidationSkill,
)
from agent_core.skills.requirement_extraction import (
    NormalizedRequirement,
    RequirementExtractionInput,
    RequirementExtractionSkill,
)


PLANNING_WORKFLOW_STEPS: tuple[str, ...] = (
    "document_ingestion",
    "requirement_extraction",
    "ambiguity_assessment",
    "repository_inspection",
    "implementation_status_classification",
    "planning_decomposition",
    "plan_validation",
    "context_capsule",
    "openproject_projection",
    "neo4j_projection",
    "weaviate_projection",
)


class PlanningWorkflowState(BaseModel):
    request: PlanningAgentRequest
    agent_state: PlanningAgentState = Field(default_factory=PlanningAgentState)
    requirement_source_refs: list[EvidenceRef] = Field(default_factory=list)
    result: PlanningAgentResult | None = None


class PlanningAgentWorkflow:
    def __init__(
        self,
        *,
        config: PlanningAgentConfig,
        dependencies: AgentDependencyContainer,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.steps = tuple(step for step in PLANNING_WORKFLOW_STEPS if step in config.skill_names)
        self.graph = _compile_planning_graph()

    async def run(
        self,
        request: PlanningAgentRequest,
        context: AgentExecutionContext,
    ) -> PlanningAgentResult:
        output = await self.graph.ainvoke(
            PlanningWorkflowState(request=request),
            context=AgentWorkflowRuntime(
                config=self.config,
                dependencies=self.dependencies,
                execution_context=context,
            ),
        )
        state = PlanningWorkflowState.model_validate(output)
        if state.result is None:
            raise RuntimeError("Planning workflow completed without a result")
        return state.result


def build_planning_agent_workflow(
    config: PlanningAgentConfig,
    dependencies: AgentDependencyContainer,
) -> PlanningAgentWorkflow:
    return PlanningAgentWorkflow(config=config, dependencies=dependencies)


def _compile_planning_graph():
    graph = StateGraph(
        PlanningWorkflowState,
        context_schema=AgentWorkflowRuntime,
    )
    graph.add_node("extract_requirements", _extract_requirements)
    graph.add_node("request_clarification", _request_clarification)
    graph.add_node("resolve_plan", _resolve_plan)
    graph.add_node("validate_plan", _validate_plan)
    graph.add_node("finalize", _finalize)

    graph.add_edge(START, "extract_requirements")
    graph.add_conditional_edges(
        "extract_requirements",
        _route_after_requirements,
        {
            "clarify": "request_clarification",
            "resolve_plan": "resolve_plan",
        },
    )
    graph.add_edge("request_clarification", "finalize")
    graph.add_conditional_edges(
        "resolve_plan",
        _route_after_plan,
        {
            "validate": "validate_plan",
            "finalize": "finalize",
        },
    )
    graph.add_edge("validate_plan", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(name="planning-agent-workflow")


async def _extract_requirements(
    state: PlanningWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[PlanningAgentConfig]],
) -> dict:
    request = state.request
    agent_state = _advance(
        state.agent_state,
        "requirement_extraction",
        trace_step="extract_requirements",
    )
    skill_result = await RequirementExtractionSkill().run(
        intent="extract requirements",
        context=SkillContext(
            project_key=request.project_id,
            session_id=str(request.execution_id),
        ),
        input_data=RequirementExtractionInput(
            original_request=request.original_request or request.objective,
            chunks=[chunk.model_dump(mode="json") for chunk in request.document_chunks],
        ).model_dump(mode="json"),
    )
    agent_state.extracted_requirements = [
        NormalizedRequirement.model_validate(item)
        for item in skill_result.output.get("requirements", [])
    ]
    await persist_workflow_state(runtime.context, agent_state)
    return {
        "agent_state": agent_state,
        "requirement_source_refs": [
            EvidenceRef.model_validate(item) for item in skill_result.source_refs
        ],
    }


def _route_after_requirements(
    state: PlanningWorkflowState,
) -> Literal["clarify", "resolve_plan"]:
    if state.request.clarification_required:
        return "clarify"
    return "resolve_plan"


async def _request_clarification(
    state: PlanningWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[PlanningAgentConfig]],
) -> dict:
    agent_state = _advance(state.agent_state, "waiting_for_clarification")
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _resolve_plan(
    state: PlanningWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[PlanningAgentConfig]],
) -> dict:
    agent_state = _advance(
        state.agent_state,
        "plan_resolution",
        trace_step="resolve_plan",
    )
    agent_state.plan = state.request.plan or await _legacy_plan_if_available(
        state.request,
        runtime.context,
    )
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


def _route_after_plan(
    state: PlanningWorkflowState,
) -> Literal["validate", "finalize"]:
    return "validate" if state.agent_state.plan is not None else "finalize"


async def _validate_plan(
    state: PlanningWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[PlanningAgentConfig]],
) -> dict:
    if not runtime.context.config.require_plan_validation:
        return {"agent_state": state.agent_state}
    plan = state.agent_state.plan
    if plan is None:
        return {"agent_state": state.agent_state}
    agent_state = _advance(
        state.agent_state,
        "plan_validation",
        trace_step="validate_plan",
    )
    validation_result = await PlanValidationSkill().run(
        intent="validate plan",
        context=SkillContext(
            project_key=state.request.project_id,
            session_id=str(state.request.execution_id),
        ),
        input_data=PlanValidationInput(plan=plan.model_dump(mode="json")).model_dump(mode="json"),
    )
    agent_state.validation = PlanValidationSkill.output_schema.model_validate(  # type: ignore[union-attr]
        validation_result.output
    )
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


async def _finalize(
    state: PlanningWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[PlanningAgentConfig]],
) -> dict:
    request = state.request
    agent_state = state.agent_state.model_copy(deep=True)
    errors: list[AgentError] = []
    clarification_questions: list[str] = []

    if request.clarification_required:
        status = AgentRunStatus.WAITING
        next_action = AgentNextAction.REQUEST_CLARIFICATION
        summary = "Planning is waiting for clarification before decomposition."
        clarification_questions = ["Clarify the requested task scope before planning."]
        phase = "waiting_for_clarification"
    elif agent_state.plan is None:
        status = AgentRunStatus.WAITING
        next_action = AgentNextAction.REQUEST_CLARIFICATION
        summary = "Requirements were extracted, but no plan was provided or generated."
        phase = "blocked"
    elif agent_state.validation is not None and not agent_state.validation.valid:
        status = AgentRunStatus.BLOCKED
        next_action = AgentNextAction.REQUEST_CLARIFICATION
        summary = "Planning produced an invalid plan."
        phase = "blocked"
        errors = [
            AgentError(
                category=AgentErrorCategory.VALIDATION_ERROR,
                message=finding.message,
                code=finding.code,
            )
            for finding in agent_state.validation.findings
            if finding.severity == "error"
        ]
    else:
        status = AgentRunStatus.SUCCEEDED
        next_action = (
            AgentNextAction.REQUEST_APPROVAL
            if runtime.context.config.approval_required
            else AgentNextAction.RUN_CODING
        )
        summary = "Planning completed."
        phase = "completed"

    agent_state = _advance(agent_state, phase, trace_step="finalize")
    state_ref = await persist_workflow_state(runtime.context, agent_state)
    artifacts: list[ArtifactReference] = []
    if agent_state.plan is not None:
        artifacts.append(
            ArtifactReference(
                artifact_id=f"plan:{request.execution_id}",
                artifact_type="plan",
                uri=f"agent-state://{state_ref.namespace}/{state_ref.key}#plan",
                title=agent_state.plan.summary,
            )
        )
    result = PlanningAgentResult(
        execution_id=request.execution_id,
        project_id=request.project_id,
        task_id=request.task_id,
        status=status,
        summary=summary,
        output_artifacts=artifacts,
        evidence=state.requirement_source_refs,
        state=state_ref,
        next_action=next_action,
        errors=errors,
        requirements=agent_state.extracted_requirements,
        plan=agent_state.plan,
        validation=agent_state.validation,
        clarification_questions=clarification_questions,
    )
    return {"agent_state": agent_state, "result": result}


async def _legacy_plan_if_available(
    request: PlanningAgentRequest,
    runtime: AgentWorkflowRuntime[PlanningAgentConfig],
) -> ProjectPlanSpec | None:
    if (
        not runtime.config.allow_legacy_planning_service
        or runtime.dependencies.planning_service is None
        or request.session_id is None
    ):
        return None
    version = await runtime.dependencies.planning_service.draft_plan(request.session_id)
    return ProjectPlanSpec.model_validate(version.plan_json)


def _advance(
    state: PlanningAgentState,
    phase: str,
    *,
    trace_step: str | None = None,
) -> PlanningAgentState:
    return state.model_copy(
        deep=True,
        update={
            "phase": phase,
            "workflow_trace": [
                *state.workflow_trace,
                trace_step or phase,
            ],
        },
    )
