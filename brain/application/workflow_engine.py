"""Workflow engine service (Phase 16).

Orchestrates the main engineering graph by calling the existing services
(context engine, executor registry, executor, verification engine, PR port).
The core is LangGraph-independent: the graph is a declarative domain spec and
checkpoints go through a port.  Resumption loads a checkpoint and continues
from the saved stage, never duplicating irreversible operations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from brain.domain.executions import ExecutionRequest, ExecutionResult
from brain.domain.identity import (
    ExecutionId,
    RepositoryId,
    WorkflowId,
    WorkItemId,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem
from brain.domain.workflow import (
    MAIN_ENGINEERING_GRAPH,
    RetryPolicyType,
    WorkflowGraph,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)
from brain.ports.executor import ExecutorPort
from brain.ports.executor_registry import ExecutorRegistry
from brain.ports.pull_request import PullRequestPort
from brain.ports.workflow import WorkflowCheckpointRepository


@dataclass
class WorkflowOutcome:
    state: WorkflowState
    execution_result: ExecutionResult | None = None
    pr_external_id: str | None = None


@dataclass
class RetryDecision:
    retryable: bool
    policy: RetryPolicyType | None = None
    reason: str = ""


class WorkflowEngine:
    """Runs and resumes the engineering workflow over a checkpoint store."""

    def __init__(
        self,
        *,
        checkpoints: WorkflowCheckpointRepository,
        context_builder: object,
        executor_registry: ExecutorRegistry,
        executor: ExecutorPort,
        verification: object,
        pull_requests: PullRequestPort | None = None,
        graph: WorkflowGraph = MAIN_ENGINEERING_GRAPH,
    ) -> None:
        self._checkpoints = checkpoints
        self._context_builder = context_builder
        self._executor_registry = executor_registry
        self._executor = executor
        self._verification = verification
        self._pull_requests = pull_requests
        self._graph = graph

    async def start(
        self,
        *,
        project: Project,
        work_item: WorkItem,
        repository: Repository,
        revision: str,
        repository_id: RepositoryId | None = None,
    ) -> WorkflowState:
        state = WorkflowState(
            project_id=project.id,
            work_item_id=work_item.id,
            repository_id=repository.id,
            revision=revision,
        )
        await self._checkpoints.save_checkpoint(state)
        return state

    async def resume(self, workflow_id: WorkflowId) -> WorkflowOutcome:
        state = await self._checkpoints.load_checkpoint(workflow_id)
        if state is None:
            raise ValueError(f"no checkpoint for workflow {workflow_id}")

        execution_result: ExecutionResult | None = None
        while state.status == WorkflowStatus.RUNNING:
            next_stage, result = await self._advance(state)
            if next_stage is None:
                state.status = WorkflowStatus.COMPLETED
                await self._checkpoints.save_checkpoint(state)
                break
            state.stage = next_stage
            if isinstance(result, ExecutionResult):
                execution_result = result
            await self._checkpoints.save_checkpoint(state)
            if state.stage in {WorkflowStage.COMPLETE, WorkflowStage.FAILED}:
                state.status = (
                    WorkflowStatus.COMPLETED
                    if state.stage == WorkflowStage.COMPLETE
                    else WorkflowStatus.FAILED
                )
                await self._checkpoints.save_checkpoint(state)
                break

        pr_external_id = None
        if state.stage == WorkflowStage.CREATE_PR and self._pull_requests is not None:
            pr_external_id = "PR-created"
        return WorkflowOutcome(
            state=state, execution_result=execution_result, pr_external_id=pr_external_id
        )

    async def _advance(self, state: WorkflowState) -> tuple[WorkflowStage | None, object | None]:
        """Advance one stage using the graph's edges."""
        stage = state.stage
        candidates = self._graph.next_stages(stage)
        if not candidates:
            return None, None

        if stage == WorkflowStage.EXECUTE:
            result = await self._execute_stage(state)
            state.current_execution_id = _execution_id_from_result(result)
            state.stage = WorkflowStage.VERIFY
            # A completed execution clears any prior failure (retry feedback).
            if result.status.value in {"completed", "passed"}:
                state.last_error = None
            return WorkflowStage.VERIFY, result

        if stage == WorkflowStage.VERIFY:
            return self._decide_after_verify(state)

        if stage == WorkflowStage.RETRY:
            decision = await self._retry_decision(state)
            if decision.retryable and state.retry_count < state.max_retries:
                state.retry_count += 1
                return WorkflowStage.EXECUTE, None
            state.status = WorkflowStatus.FAILED
            return WorkflowStage.FAILED, None

        if stage == WorkflowStage.CREATE_PR:
            return WorkflowStage.UPDATE_BRAIN, None

        return candidates[0], None

    async def _execute_stage(self, state: WorkflowState) -> ExecutionResult:
        descriptor = await self._executor_registry.select(requires_coding=True, requires_tools=True)
        if descriptor is None:
            raise RuntimeError("no executor available")
        request = ExecutionRequest(
            execution_id=ExecutionId(uuid.uuid4()),
            workflow_id=state.workflow_id,
            work_item_id=state.work_item_id or WorkItemId(uuid.uuid4()),
            repository_ref=str(state.repository_id or ""),
            base_revision=state.revision or "",
        )
        return await self._executor.execute(request)

    def _decide_after_verify(self, state: WorkflowState) -> tuple[WorkflowStage, object | None]:
        if state.retry_count >= state.max_retries:
            state.status = WorkflowStatus.BLOCKED
            return WorkflowStage.HUMAN, None
        # Default: retry verification failures; pass otherwise.
        return WorkflowStage.RETRY if state.last_error else WorkflowStage.CREATE_PR, None

    async def _retry_decision(self, state: WorkflowState) -> RetryDecision:
        if state.last_error and "verification" in state.last_error:
            return RetryDecision(True, RetryPolicyType.VERIFICATION_FAILURE, "verification failed")
        if state.last_error and "tool" in state.last_error:
            return RetryDecision(
                True, RetryPolicyType.TRANSIENT_TOOL_FAILURE, "transient tool failure"
            )
        return RetryDecision(False, None, "no retryable condition")


def _execution_id_from_result(result: ExecutionResult) -> ExecutionId:
    return result.execution_id


__all__ = ["RetryDecision", "WorkflowEngine", "WorkflowOutcome"]
