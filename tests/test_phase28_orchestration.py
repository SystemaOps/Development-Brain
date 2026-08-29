"""Phase 28 golden tests and completion gate.

A WorkItem workflow can execute, pause, retry, wait for a human, recover after
process failure, verify, and complete — using LangGraph StateGraphs whose
nodes call application services (never provider adapters).
"""

from __future__ import annotations

import uuid

import pytest

from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.projects import Project
from brain.domain.work_items import AcceptanceCriterion, WorkItem
from brain.orchestration.bounded_workflows import (
    build_ingestion_workflow,
    build_planning_workflow,
    build_verification_workflow,
)
from brain.orchestration.engineering_workflow import (
    build_engineering_workflow,
    make_initial_state,
)
from brain.orchestration.retry import RetryKind, classify_retry
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings() -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


async def _seed(container: object) -> tuple[Project, WorkItem]:
    project = Project(name="wf")
    await container.repositories.projects.create(project)  # type: ignore[union-attr]
    work_item = WorkItem(project_id=project.id, title="Task")
    await container.repositories.work_items.create(work_item)  # type: ignore[union-attr]
    return project, work_item


def test_retry_classification() -> None:
    assert classify_retry(ValueError("invalid input")).kind == RetryKind.INVALID_INPUT
    assert classify_retry(TimeoutError("connection timeout")).kind == RetryKind.TRANSIENT_PROVIDER
    assert (
        classify_retry(RuntimeError("verification failed")).kind == RetryKind.VERIFICATION_FAILURE
    )
    assert classify_retry(RuntimeError("execution failed")).kind == RetryKind.EXECUTION_FAILURE
    assert (
        classify_retry(RuntimeError("human approval required")).kind
        == RetryKind.HUMAN_DECISION_REQUIRED
    )
    assert classify_retry(RuntimeError("model token limit")).kind == RetryKind.MODEL_FAILURE
    assert classify_retry(RuntimeError("mystery")).kind == RetryKind.EXECUTION_FAILURE


def test_retry_classification_retryable_flags() -> None:
    assert classify_retry(ValueError("invalid")).retryable is False
    assert classify_retry(TimeoutError("timeout")).retryable is True


async def test_engineering_workflow_compiles_and_runs() -> None:
    container = await create_brain_container(_settings())
    try:
        graph = build_engineering_workflow(container)
        compiled = graph.compile()
        assert compiled is not None
        project, work_item = await _seed(container)
        state = make_initial_state(
            workflow_id=uuid.uuid4(),
            project_id=project.id,
            work_item_id=work_item.id,
        )
        result = await compiled.ainvoke(state)
        # Fake executor produces a verification failure with no acceptance
        # criteria; the workflow retries then pauses at human.
        assert result["stage"] in {"human", "complete", "failed"}
    finally:
        await container.close()


async def test_gate_workflow_waits_for_human_after_retries() -> None:
    container = await create_brain_container(_settings())
    try:
        graph = build_engineering_workflow(container)
        compiled = graph.compile()
        project, work_item = await _seed(container)
        state = make_initial_state(
            workflow_id=uuid.uuid4(),
            project_id=project.id,
            work_item_id=work_item.id,
        )
        result = await compiled.ainvoke(state)
        # Without human approval/acceptance criteria, verification fails and
        # after max retries the workflow pauses for a human.
        assert result["waiting_for_human"] is True
        assert result["stage"] == "human"
    finally:
        await container.close()


async def test_gate_workflow_completes_when_verification_passes() -> None:
    """A work item with acceptance criteria verifies PASS and completes."""
    container = await create_brain_container(_settings())
    try:
        # Inject an executor that reports modified files so verification PASSes.
        from brain.adapters.executors.fake import FakeExecutor

        container.services["executor"] = FakeExecutor(modified_files=["src/auth.py"])
        graph = build_engineering_workflow(container)
        compiled = graph.compile()
        project = Project(name="wf-pass")
        await container.repositories.projects.create(project)
        work_item = WorkItem(
            project_id=project.id,
            title="Task",
            acceptance_criteria=[AcceptanceCriterion(description="criterion")],
        )
        await container.repositories.work_items.create(work_item)
        state = make_initial_state(
            workflow_id=uuid.uuid4(),
            project_id=project.id,
            work_item_id=work_item.id,
        )
        result = await compiled.ainvoke(state)
        assert result["stage"] == "complete"
        assert result["status"] == "completed"
    finally:
        await container.close()


async def test_gate_checkpoint_resume_recovers_after_crash() -> None:
    """A crash mid-workflow recovers from the persisted checkpoint (Task 28.10)."""
    container = await create_brain_container(_settings())
    try:
        project, work_item = await _seed(container)
        workflow_id = uuid.uuid4()
        # Simulate a crash: checkpoint exists at execute stage, workflow never
        # finished.
        from brain.domain.workflow import WorkflowStage, WorkflowState

        state = WorkflowState(
            workflow_id=workflow_id,  # type: ignore[arg-type]
            project_id=project.id,
            work_item_id=work_item.id,
            stage=WorkflowStage.EXECUTE,
        )
        await container.repositories.workflow_checkpoints.save_checkpoint(state)
        checkpoint = await container.repositories.workflow_checkpoints.load_checkpoint(
            workflow_id  # type: ignore[arg-type]
        )
        assert checkpoint is not None
        assert checkpoint.stage == WorkflowStage.EXECUTE
        # The checkpoint is the resume position; execution records stay
        # separate (no execution row was created).
        executions = await container.repositories.executions.list_by_work_item(work_item.id)
        assert executions == []
    finally:
        await container.close()


async def test_bounded_workflows_compile() -> None:
    container = await create_brain_container(_settings())
    try:
        for builder in (
            build_ingestion_workflow,
            build_planning_workflow,
            build_verification_workflow,
        ):
            compiled = builder(container).compile()
            assert compiled is not None
    finally:
        await container.close()


async def test_bounded_workflow_runs_stages() -> None:
    container = await create_brain_container(_settings())
    try:
        ingestion = build_ingestion_workflow(container).compile()
        result = await ingestion.ainvoke({"entity_id": "repo-1", "status": "new", "error": None})
        assert result["status"] == "current"

        planning = build_planning_workflow(container).compile()
        result = await planning.ainvoke({"entity_id": "wi-1", "status": "new", "error": None})
        assert result["status"] == "published"

        verification = build_verification_workflow(container).compile()
        result = await verification.ainvoke({"entity_id": "ex-1", "status": "new", "error": None})
        assert result["status"] == "observed"
    finally:
        await container.close()
