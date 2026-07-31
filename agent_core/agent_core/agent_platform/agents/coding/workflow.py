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
from agent_core.agent_platform.agents.coding.config import (
    CodingAgentConfig,
)
from agent_core.agent_platform.agents.coding.state import (
    CodingAgentRequest,
    CodingAgentResult,
    CodingAgentState,
)
from agent_core.agent_platform.runtime.dependency_container import (
    AgentDependencyContainer,
)
from agent_core.agent_platform.runtime.execution_context import (
    AgentExecutionContext,
)
from agent_core.domain.enums import CodingAttemptStatus


CODING_WORKFLOW_STEPS: tuple[str, ...] = (
    "load_task_context",
    "inspect_repository",
    "policy_check",
    "apply_patch",
    "run_quality_checks",
    "capture_evidence",
    "decide_retry_or_handoff",
)


class CodingWorkflowState(BaseModel):
    request: CodingAgentRequest
    agent_state: CodingAgentState = Field(default_factory=CodingAgentState)
    errors: list[AgentError] = Field(default_factory=list)
    result: CodingAgentResult | None = None


class CodingAgentWorkflow:
    def __init__(
        self,
        *,
        config: CodingAgentConfig,
        dependencies: AgentDependencyContainer,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.steps = CODING_WORKFLOW_STEPS
        self.graph = _compile_coding_graph()

    async def run(
        self,
        request: CodingAgentRequest,
        context: AgentExecutionContext,
    ) -> CodingAgentResult:
        output = await self.graph.ainvoke(
            CodingWorkflowState(request=request),
            context=AgentWorkflowRuntime(
                config=self.config,
                dependencies=self.dependencies,
                execution_context=context,
            ),
        )
        state = CodingWorkflowState.model_validate(output)
        if state.result is None:
            raise RuntimeError("Coding workflow completed without a result")
        return state.result


def build_coding_agent_workflow(
    config: CodingAgentConfig,
    dependencies: AgentDependencyContainer,
) -> CodingAgentWorkflow:
    return CodingAgentWorkflow(config=config, dependencies=dependencies)


def _compile_coding_graph():
    graph = StateGraph(
        CodingWorkflowState,
        context_schema=AgentWorkflowRuntime,
    )
    graph.add_node("load_task_context", _load_task_context)
    graph.add_node("execute_coding_attempt", _execute_coding_attempt)
    graph.add_node("finalize", _finalize)

    graph.add_edge(START, "load_task_context")
    graph.add_conditional_edges(
        "load_task_context",
        _route_after_context,
        {
            "execute": "execute_coding_attempt",
            "finalize": "finalize",
        },
    )
    graph.add_edge("execute_coding_attempt", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(name="coding-agent-workflow")


async def _load_task_context(
    state: CodingWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[CodingAgentConfig]],
) -> dict:
    agent_state = _advance(state.agent_state, "load_task_context")
    agent_state.coding_attempt = state.request.coding_attempt
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state}


def _route_after_context(
    state: CodingWorkflowState,
) -> Literal["execute", "finalize"]:
    if state.agent_state.coding_attempt is None:
        return "finalize"
    return "execute"


async def _execute_coding_attempt(
    state: CodingWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[CodingAgentConfig]],
) -> dict:
    service = runtime.context.dependencies.coding_service
    if service is None:
        return {"agent_state": state.agent_state}

    agent_state = _advance(state.agent_state, "execute_coding_attempt")
    await persist_workflow_state(runtime.context, agent_state)
    errors = list(state.errors)
    try:
        agent_state.result = await service.run_explicit_attempt(
            project_key=state.request.project_id,
            request=state.request.coding_attempt,
        )
    except Exception as exc:
        errors.append(
            AgentError(
                category=AgentErrorCategory.TOOL_EXECUTION_ERROR,
                message=str(exc),
                code="coding_attempt_failed",
            )
        )
        agent_state = agent_state.model_copy(update={"phase": "attempt_failed"})
    else:
        agent_state = agent_state.model_copy(update={"phase": "attempt_finished"})
    await persist_workflow_state(runtime.context, agent_state)
    return {"agent_state": agent_state, "errors": errors}


async def _finalize(
    state: CodingWorkflowState,
    runtime: Runtime[AgentWorkflowRuntime[CodingAgentConfig]],
) -> dict:
    request = state.request
    coding_result = state.agent_state.result
    errors = list(state.errors)

    if runtime.context.dependencies.coding_service is None:
        status = AgentRunStatus.BLOCKED
        next_action = AgentNextAction.ESCALATE
        summary = "Coding agent is missing CodingService dependency."
        phase = "blocked"
        errors.append(
            AgentError(
                category=AgentErrorCategory.DEPENDENCY_ERROR,
                message="CodingService dependency is required for coding execution.",
                code="missing_coding_service",
            )
        )
    elif coding_result is None:
        status = AgentRunStatus.FAILED
        next_action = AgentNextAction.RETRY
        summary = "Coding attempt failed before producing a result."
        phase = "failed"
    elif coding_result.status == CodingAttemptStatus.SUCCEEDED:
        status = AgentRunStatus.SUCCEEDED
        next_action = AgentNextAction.RUN_VERIFICATION
        summary = "Coding attempt completed and is ready for verification."
        phase = "completed"
    elif coding_result.status == CodingAttemptStatus.BLOCKED:
        status = AgentRunStatus.BLOCKED
        next_action = AgentNextAction.ESCALATE
        summary = "Coding attempt is blocked by policy or repository state."
        phase = "blocked"
    else:
        status = AgentRunStatus.FAILED
        next_action = AgentNextAction.RETRY
        summary = "Coding attempt failed quality checks."
        phase = "failed"

    agent_state = _advance(state.agent_state, phase, trace_step="finalize")
    state_ref = await persist_workflow_state(runtime.context, agent_state)
    artifacts: list[ArtifactReference] = []
    evidence = []
    if coding_result is not None:
        artifacts.append(
            ArtifactReference(
                artifact_id=f"coding-result:{request.execution_id}",
                artifact_type="coding_result",
                uri=(f"agent-state://{state_ref.namespace}/{state_ref.key}#coding_result"),
                title=f"Coding result for {request.task_id}",
                metadata={"changed_files": coding_result.changed_files},
            )
        )
        evidence = coding_result.evidence
        errors.extend(
            AgentError(
                category=AgentErrorCategory.TOOL_EXECUTION_ERROR,
                message=message,
                code="coding_attempt_error",
            )
            for message in coding_result.errors
        )
    result = CodingAgentResult(
        execution_id=request.execution_id,
        project_id=request.project_id,
        task_id=request.task_id,
        status=status,
        summary=summary,
        output_artifacts=artifacts,
        evidence=evidence,
        state=state_ref,
        next_action=next_action,
        errors=errors,
        coding_result=coding_result,
    )
    return {"agent_state": agent_state, "errors": errors, "result": result}


def _advance(
    state: CodingAgentState,
    phase: str,
    *,
    trace_step: str | None = None,
) -> CodingAgentState:
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
