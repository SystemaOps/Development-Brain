"""Phase 37 golden tests and completion gate.

Pi Executor Runtime Integration: the configured coding executor runs inside the
operational Brain runtime (Task 37.2), capability health reports Pi (37.3),
brain retrieval tools call application services (37.4), every execution
records its isolated workspace (37.5), and Pi failures mark the execution
failed without terminating the worker (37.6).
"""

from __future__ import annotations

from typing import Any

import pytest

from brain.adapters.executors.pi import (
    PiExecutionError,
    PiExecutor,
)
from brain.application.brain_tools import TOOL_REGISTRY, BrainTools
from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    ExecutorSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.executions import (
    Execution,
    ExecutionRequest,
    ExecutionStatus,
)
from brain.domain.identity import (
    new_actor_id,
    new_execution_id,
    new_project_id,
    new_work_item_id,
    new_workflow_id,
)
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings(executors: ExecutorSettings | None = None) -> BrainSettings:
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
        executors=executors or ExecutorSettings(coding_provider="fake"),
    )


class _FakePi:
    """A transport that mirrors a Pi session without any Pi binary."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.seen: dict[str, object] = {}

    async def round_trip(self, payload: dict[str, object]) -> dict[str, object]:
        if self._fail:
            raise PiExecutionError("model timeout")
        self.seen = dict(payload)
        return {
            "status": "completed",
            "modified_files": ["src/service.py"],
            "commands_executed": ["uv run pytest -q"],
            "tests_executed": ["tests/test_service.py"],
            "observations": ["implemented the service"],
        }


def _request(**overrides: Any) -> ExecutionRequest:
    values: dict[str, Any] = {
        "execution_id": new_execution_id(),
        "workflow_id": new_workflow_id(),
        "work_item_id": new_work_item_id(),
        "repository_ref": "git@example.com:team/repo.git",
        "base_revision": "abc123",
    }
    values.update(overrides)
    return ExecutionRequest(**values)


async def test_gate_queued_work_item_executes_through_pi() -> None:
    """A queued WorkItem executes through Pi with a bounded request (37.2/37.4)."""
    executor = PiExecutor(transport=_FakePi())
    request = _request(
        base_branch="main",
        working_branch="brain/work-item/abc",
        worktree_path="/tmp/brain-workspaces/x",
    )
    result = await executor.execute(request)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.modified_files == ["src/service.py"]
    assert result.tests_executed == ["tests/test_service.py"]


async def test_pi_payload_carries_workspace_isolation_fields() -> None:
    """The Pi payload records repository/branch/worktree (37.5)."""
    fake = _FakePi()
    executor = PiExecutor(transport=fake)
    await executor.execute(
        _request(
            base_branch="main",
            working_branch="brain/wi/deadbeef",
            worktree_path="/tmp/brain-workspaces/deadbeef",
        )
    )
    assert fake.seen["repository_ref"] == "git@example.com:team/repo.git"
    assert fake.seen["base_revision"] == "abc123"
    assert fake.seen["base_branch"] == "main"
    assert fake.seen["working_branch"] == "brain/wi/deadbeef"
    assert fake.seen["worktree_path"] == "/tmp/brain-workspaces/deadbeef"
    tools_seen = fake.seen.get("tools")
    assert isinstance(tools_seen, list)
    assert "brain_get_architecture_constraints" in tools_seen
    assert "brain_search_project_knowledge" in tools_seen


async def test_pi_failure_isolation_returns_failed_result() -> None:
    """A failing Pi transport marks the execution FAILED, never raises (37.6)."""
    executor = PiExecutor(transport=_FakePi(fail=True))
    result = await executor.execute(_request())
    assert result.status == ExecutionStatus.FAILED
    assert result.blockers
    assert "pi transport failure" in result.blockers[0]


def test_brain_tools_registry_has_all_phase_37_tools() -> None:
    """Executors can call the full Phase 37 tool set (37.4)."""
    assert {
        "brain_get_task",
        "brain_get_symbol_context",
        "brain_find_related_files",
        "brain_find_related_tests",
        "brain_get_requirement",
        "brain_get_architecture_constraints",
        "brain_search_project_knowledge",
        "brain_request_more_context",
    } <= TOOL_REGISTRY


async def test_tools_call_application_services_not_databases() -> None:
    """BrainTools delegates to JustInTimeRetrieval (application), never repos."""
    container = await create_brain_container(_settings())
    try:
        jit = container.services["jit_retrieval"]
        from brain.application.jit_retrieval import JustInTimeRetrieval

        assert isinstance(jit, JustInTimeRetrieval)
        tools = BrainTools(work_items=container.repositories.work_items, jit=jit)
        result = await tools.brain_get_architecture_constraints(new_project_id())
        assert isinstance(result, list)
        knowledge = await tools.brain_search_project_knowledge("auth")
        assert isinstance(knowledge, list)
    finally:
        await container.close()


async def test_gate_pi_provider_registered_and_capability_available() -> None:
    """coding_provider=pi registers the Pi executor + AVAILABLE capability."""
    container = await create_brain_container(_settings(ExecutorSettings(coding_provider="pi")))
    try:
        assert container.capabilities()["coding_executor"] == "AVAILABLE"
        descriptors = await container.executor_registry.list()
        assert any(d.name == "pi" for d in descriptors)
        from brain.adapters.executors.pi import PiExecutor

        assert isinstance(container.services["executor"], PiExecutor)
        assert container.is_ready() is True
    finally:
        await container.close()


async def test_gate_fake_default_keeps_brain_ready() -> None:
    """The fake default stays available and the Brain ready."""
    container = await create_brain_container(_settings())
    try:
        assert container.capabilities()["coding_executor"] == "AVAILABLE"
        descriptors = await container.executor_registry.list()
        assert any(d.name == "fake" for d in descriptors)
        assert container.is_ready() is True
    finally:
        await container.close()


async def test_workspace_manager_degrades_without_source_control() -> None:
    """Without source control the workspace is planned, not isolated (37.5)."""
    container = await create_brain_container(_settings())
    try:
        from brain.application.workspace_manager import WorkspaceManager

        workspace_manager = container.services["workspace_manager"]
        assert isinstance(workspace_manager, WorkspaceManager)
        assert workspace_manager.isolated is False
    finally:
        await container.close()


async def test_execution_records_workspace_isolation_in_db() -> None:
    """Every execution persists repository/branch/worktree (37.5)."""
    container = await create_brain_container(_settings())
    try:
        from brain.domain.projects import Project

        project = Project(name="pi-run")
        await container.repositories.projects.create(project)
        from brain.domain.repositories import Repository

        repository = Repository(
            project_id=project.id,
            name="repo",
            clone_url="git@example.com:team/repo.git",
        )
        await container.repositories.repositories.create(repository)
        from brain.domain.work_items import WorkItem

        work_item = WorkItem(project_id=project.id, title="pi task")
        await container.repositories.work_items.create(work_item)

        execution = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=work_item.id,
            executor_id=new_actor_id(),
            status=ExecutionStatus.COMPLETED,
            base_branch="main",
            working_branch="brain/wi/deadbeef",
            worktree_path="/tmp/brain-workspaces/deadbeef",
        )
        await container.repositories.executions.create(execution)
        stored = await container.repositories.executions.get(execution.id)
        assert stored is not None
        assert stored.base_branch == "main"
        assert stored.working_branch == "brain/wi/deadbeef"
        assert stored.worktree_path == "/tmp/brain-workspaces/deadbeef"
    finally:
        await container.close()
