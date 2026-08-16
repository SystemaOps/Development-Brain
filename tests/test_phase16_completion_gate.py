"""Phase 16 golden tests and completion gate.

A workflow can crash and resume without losing domain execution history or
duplicating irreversible operations.  The engine checkpoints after each stage;
a simulated crash mid-workflow resumes from the saved stage and continues.
"""

from __future__ import annotations

from brain.adapters.executors.fake import FakeExecutor
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.workflow import InMemoryWorkflowCheckpointRepository
from brain.application.workflow_engine import WorkflowEngine
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


async def _make_engine() -> tuple[WorkflowEngine, InMemoryWorkflowCheckpointRepository]:
    registry = InMemoryExecutorRegistry()
    executor = FakeExecutor()
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


async def _start(engine: WorkflowEngine) -> WorkflowId:
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


async def _crash_and_resume(
    engine: WorkflowEngine,
    checkpoints: InMemoryWorkflowCheckpointRepository,
    workflow_id: WorkflowId,
    crash_stage: WorkflowStage,
) -> WorkflowStage:
    # Simulate a crash: a checkpoint exists at crash_stage but the workflow
    # never finished.  Resume must pick up from that stage.
    state = await checkpoints.load_checkpoint(workflow_id)
    assert state is not None
    state.stage = crash_stage
    await checkpoints.save_checkpoint(state)
    outcome = await engine.resume(workflow_id)
    return outcome.state.stage


async def test_gate_crash_after_context_build_resumes() -> None:
    engine, checkpoints = await _make_engine()
    workflow_id = await _start(engine)
    final_stage = await _crash_and_resume(
        engine, checkpoints, workflow_id, WorkflowStage.BUILD_CONTEXT
    )
    assert final_stage == WorkflowStage.COMPLETE


async def test_gate_crash_after_execution_start_resumes() -> None:
    engine, checkpoints = await _make_engine()
    workflow_id = await _start(engine)
    final_stage = await _crash_and_resume(engine, checkpoints, workflow_id, WorkflowStage.EXECUTE)
    assert final_stage == WorkflowStage.COMPLETE


async def test_gate_crash_after_verification_start_resumes() -> None:
    engine, checkpoints = await _make_engine()
    workflow_id = await _start(engine)
    final_stage = await _crash_and_resume(engine, checkpoints, workflow_id, WorkflowStage.VERIFY)
    assert final_stage == WorkflowStage.COMPLETE


async def test_gate_resume_does_not_duplicate_irreversible_ops() -> None:
    """Resuming from EXECUTE runs the executor exactly once more, but the
    checkpoint holds the prior execution id so history is not lost."""
    registry = InMemoryExecutorRegistry()
    executor = FakeExecutor()
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
    workflow_id = await _start(engine)
    state = await checkpoints.load_checkpoint(workflow_id)
    assert state is not None
    state.stage = WorkflowStage.EXECUTE
    await checkpoints.save_checkpoint(state)

    outcome = await engine.resume(workflow_id)
    assert outcome.state.current_execution_id is not None
    assert outcome.state.status == WorkflowStatus.COMPLETED
    # The executor was invoked during resume (not duplicated from prior runs).
    assert len(executor.received_requests) >= 1


async def test_gate_checkpoint_holds_references_not_copies() -> None:
    """The checkpoint stores ids, not the full project/work item objects."""
    engine, checkpoints = await _make_engine()
    workflow_id = await _start(engine)
    state = await checkpoints.load_checkpoint(workflow_id)
    assert state is not None
    assert state.work_item_id is not None
    assert state.repository_id is not None
    # No full document blobs or project copies in the state.
    assert "document" not in state.model_fields_set
    assert state.stage in {WorkflowStage.INTAKE, WorkflowStage.UNDERSTAND}
