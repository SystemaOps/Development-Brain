from __future__ import annotations

from pydantic import BaseModel, SerializeAsAny

from agent_core.agent_platform.agents.base.contracts import (
    AgentError,
    AgentErrorCategory,
    AgentNextAction,
    AgentResult,
    AgentRunStatus,
    StateReference,
)
from agent_core.agent_platform.agents.base.errors import (
    AgentCheckpointError,
    AgentConfigurationError,
    AgentDependencyError,
    AgentValidationError,
)
from agent_core.agent_platform.agents.base.lifecycle import execute_agent_lifecycle
from agent_core.agent_platform.factory.agent_factory import AgentFactory
from agent_core.agent_platform.orchestration.contracts import (
    AgentExecutionRequest,
    AgentResultStore,
    InMemoryAgentResultStore,
    PersistedAgentResult,
)
from agent_core.agent_platform.orchestration.routing import (
    AgentRouteDecision,
    route_transition,
)
from agent_core.agent_platform.orchestration.transitions import decide_next_transition
from agent_core.agent_platform.runtime.dependency_container import AgentDependencyContainer
from agent_core.agent_platform.runtime.event_bus import (
    AgentLifecycleEvent,
    AgentLifecycleEventType,
)
from agent_core.agent_platform.runtime.execution_context import (
    AgentExecutionContext,
    CheckpointIdentity,
)


class AgentOrchestrationResult(BaseModel):
    result: SerializeAsAny[AgentResult]
    persisted: PersistedAgentResult
    route: AgentRouteDecision


class AgentOrchestrator:
    def __init__(
        self,
        *,
        factory: AgentFactory,
        dependencies: AgentDependencyContainer | None = None,
        result_store: AgentResultStore | None = None,
    ) -> None:
        self.factory = factory
        self.dependencies = dependencies or factory.dependencies
        self.result_store = (
            result_store or self.dependencies.result_store or InMemoryAgentResultStore()
        )

    async def run_once(self, execution: AgentExecutionRequest) -> AgentOrchestrationResult:
        context = self._context(execution)
        await self._emit(context, AgentLifecycleEventType.CREATED, AgentRunStatus.CREATED.value)
        await self._emit(context, AgentLifecycleEventType.STARTED, AgentRunStatus.RUNNING.value)
        try:
            agent = self.factory.create(agent_type=execution.agent_type, config=execution.config)
            await self._emit(
                context,
                AgentLifecycleEventType.STEP_STARTED,
                AgentRunStatus.RUNNING.value,
                step_name="agent.execute",
            )
            result = await execute_agent_lifecycle(
                agent, request=execution.request, context=context
            )
            await self._emit(
                context,
                AgentLifecycleEventType.STEP_COMPLETED,
                result.status.value,
                step_name="agent.execute",
            )
            await self._emit(context, AgentLifecycleEventType.COMPLETED, result.status.value)
        except Exception as exc:
            result = await self._failure_result(execution, context, exc)
            await self._emit(
                context,
                AgentLifecycleEventType.FAILED,
                result.status.value,
                metadata={"error": str(exc)},
            )
        persisted = await self.result_store.persist(result)
        await self._emit(
            context,
            AgentLifecycleEventType.RESULT_PERSISTED,
            result.status.value,
            metadata={"result_id": str(persisted.result_id)},
        )
        transition = decide_next_transition(result, execution.config)
        route = route_transition(transition, current_agent_type=execution.agent_type)
        await self._emit(
            context,
            AgentLifecycleEventType.TRANSITION_REQUESTED,
            result.status.value,
            metadata={
                "next_action": transition.next_action.value,
                "next_agent_type": route.next_agent_type,
                "reason": route.reason,
                "requires_approval": route.requires_approval,
                "escalate": route.escalate,
            },
        )
        return AgentOrchestrationResult(result=result, persisted=persisted, route=route)

    def _context(self, execution: AgentExecutionRequest) -> AgentExecutionContext:
        agent_instance_id = f"{execution.agent_type}:{execution.config.implementation}"
        checkpoint = CheckpointIdentity(
            project_id=execution.request.project_id,
            workflow_id=execution.workflow_id,
            agent_type=execution.agent_type,
            agent_instance_id=agent_instance_id,
            execution_id=execution.request.execution_id,
            thread_id=f"{execution.request.project_id}:{execution.request.task_id or 'project'}:{execution.agent_type}",
        )
        return AgentExecutionContext(
            execution_id=execution.request.execution_id,
            project_id=execution.request.project_id,
            task_id=execution.request.task_id,
            workflow_id=execution.workflow_id,
            agent_type=execution.agent_type,
            agent_instance_id=agent_instance_id,
            thread_id=checkpoint.thread_id,
            checkpoint=checkpoint,
            correlation_id=execution.correlation_id,
            approval_required=execution.config.approval_required,
        )

    async def _emit(
        self,
        context: AgentExecutionContext,
        event_type: AgentLifecycleEventType,
        status: str,
        *,
        step_name: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        await self.dependencies.event_bus.emit(
            AgentLifecycleEvent(
                event_type=event_type,
                execution_id=context.execution_id,
                project_id=context.project_id,
                task_id=context.task_id,
                agent_type=context.agent_type,
                agent_instance_id=context.agent_instance_id,
                status=status,
                step_name=step_name,
                correlation_id=context.correlation_id,
                metadata=metadata or {},
            )
        )

    async def _failure_result(
        self,
        execution: AgentExecutionRequest,
        context: AgentExecutionContext,
        exc: Exception,
    ) -> AgentResult:
        state_ref: StateReference | None = None
        try:
            previous_state = await self.dependencies.checkpoint_store.load(
                identity=context.checkpoint
            )
            failure_state = {
                "phase": "failed",
                "agent_type": execution.agent_type,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if previous_state is not None:
                failure_state["last_workflow_state"] = previous_state
            checkpoint_id = await self.dependencies.checkpoint_store.save(
                identity=context.checkpoint,
                state=failure_state,
            )
            state_ref = StateReference(
                namespace=context.checkpoint.agent_type,
                key=context.checkpoint.key,
                checkpoint_id=checkpoint_id,
            )
        except Exception as checkpoint_exc:
            exc = AgentCheckpointError(f"{exc}; checkpoint save failed: {checkpoint_exc}")

        category = _error_category(exc)
        return AgentResult(
            execution_id=execution.request.execution_id,
            project_id=execution.request.project_id,
            task_id=execution.request.task_id,
            agent_type=execution.agent_type,
            status=AgentRunStatus.FAILED,
            summary=f"{execution.agent_type} agent failed before completing.",
            state=state_ref,
            next_action=AgentNextAction.RETRY
            if category == AgentErrorCategory.RETRYABLE_ERROR
            else AgentNextAction.ESCALATE,
            errors=[
                AgentError(
                    category=category,
                    message=str(exc),
                    retryable=category == AgentErrorCategory.RETRYABLE_ERROR,
                    code=type(exc).__name__,
                    details={"workflow_id": execution.workflow_id},
                )
            ],
        )


def _error_category(exc: Exception) -> AgentErrorCategory:
    if isinstance(exc, AgentValidationError):
        return AgentErrorCategory.VALIDATION_ERROR
    if isinstance(exc, AgentConfigurationError):
        return AgentErrorCategory.CONFIGURATION_ERROR
    if isinstance(exc, AgentDependencyError):
        return AgentErrorCategory.DEPENDENCY_ERROR
    if isinstance(exc, AgentCheckpointError):
        return AgentErrorCategory.CHECKPOINT_ERROR
    return AgentErrorCategory.NON_RETRYABLE_ERROR
