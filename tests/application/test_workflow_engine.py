"""Unit tests for the Phase 16 workflow engine."""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.executors.fake import FakeExecutor
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.workflow import InMemoryWorkflowCheckpointRepository
from brain.application.workflow_engine import WorkflowEngine
from brain.domain.executions import ExecutionStatus
from brain.domain.executor import (
    ExecutorCapabilities,
    ExecutorDescriptor,
    ExecutorKind,
)
from brain.domain.identity import WorkflowId
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem
from brain.domain.workflow import WorkflowStage, WorkflowStatus


async def _engine(
    *,
    executor_status: ExecutionStatus = ExecutionStatus.COMPLETED,
) -> tuple[WorkflowEngine, InMemoryWorkflowCheckpointRepository]:
    registry = InMemoryExecutorRegistry()
    executor = FakeExecutor(status=executor_status)
    await registry.register(
        ExecutorDescriptor(
            name="fake",
            kind=ExecutorKind.FAKE,
            capabilities=ExecutorCapabilities(coding=True, tool_support=True, context_window=32000),
        )
    )
    checkpoints = InMemoryWorkflowCheckpointRepository()
    engine = WorkflowEngine(
        checkpoints=checkpoints,
        context_builder=object(),
        executor_registry=registry,
        executor=executor,
        verification=object(),
    )
    return engine, checkpoints


async def _start(
    engine: WorkflowEngine,
) -> WorkflowId:
    project = Project(name="auth")
    work_item = WorkItem(project_id=project.id, title="Implement login")
    repository = Repository(project_id=project.id, name="auth", clone_url="git@example:auth.git")
    state = await engine.start(
        project=project,
        work_item=work_item,
        repository=repository,
        revision="abc",
        repository_id=repository.id,
    )
    return state.workflow_id


async def test_engine_starts_and_saves_checkpoint() -> None:
    engine, checkpoints = await _engine()
    await _start(engine)
    assert len(checkpoints._checkpoints) == 1


async def test_engine_resume_completes() -> None:
    engine, checkpoints = await _engine()
    workflow_id = await _start(engine)
    outcome = await engine.resume(workflow_id)
    assert outcome.state.status == WorkflowStatus.COMPLETED
    assert outcome.state.stage == WorkflowStage.COMPLETE


async def test_engine_retries_on_verification_failure() -> None:
    engine, checkpoints = await _engine()
    workflow_id = await _start(engine)
    state = await checkpoints.load_checkpoint(workflow_id)
    assert state is not None
    state.stage = WorkflowStage.VERIFY
    state.last_error = "verification failed"
    await checkpoints.save_checkpoint(state)
    outcome = await engine.resume(workflow_id)
    assert outcome.state.status == WorkflowStatus.COMPLETED
    assert outcome.state.retry_count >= 1


async def test_engine_blocks_after_max_retries() -> None:
    engine, checkpoints = await _engine()
    workflow_id = await _start(engine)
    state = await checkpoints.load_checkpoint(workflow_id)
    assert state is not None
    state.stage = WorkflowStage.VERIFY
    state.last_error = "verification failed"
    state.retry_count = state.max_retries
    await checkpoints.save_checkpoint(state)
    outcome = await engine.resume(workflow_id)
    assert outcome.state.status in {WorkflowStatus.FAILED, WorkflowStatus.BLOCKED}


async def test_engine_resumes_from_context_build() -> None:
    engine, checkpoints = await _engine()
    workflow_id = await _start(engine)
    state = await checkpoints.load_checkpoint(workflow_id)
    assert state is not None
    state.stage = WorkflowStage.BUILD_CONTEXT
    await checkpoints.save_checkpoint(state)
    outcome = await engine.resume(workflow_id)
    assert outcome.state.status == WorkflowStatus.COMPLETED


async def test_engine_unknown_workflow_raises() -> None:
    engine, _ = await _engine()
    with pytest.raises(ValueError):
        await engine.resume(WorkflowId(uuid.UUID(int=1)))
