"""Unit tests for the Phase 12 executor abstraction."""

from __future__ import annotations

import uuid

from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.executors.fake import FakeExecutor
from brain.adapters.executors.pi import PiExecutor
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryRequirementRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.application.brain_tools import TOOL_REGISTRY, BrainTools
from brain.application.execution_request_builder import ExecutionRequestBuilder
from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.jit_retrieval import JustInTimeRetrieval
from brain.application.workspace_manager import Workspace, WorkspaceManager
from brain.domain.executions import (
    ExecutionRequest,
    ExecutionStatus,
)
from brain.domain.executor import (
    ExecutorCapabilities,
    ExecutorDescriptor,
    ExecutorKind,
    ModelCapabilityProfile,
    ModelDeployment,
)
from brain.domain.identity import (
    RepositoryId,
    WorkflowId,
    new_execution_id,
    new_project_id,
    new_work_item_id,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem
from brain.ports.executor import ExecutorPort


class _FakeSourceControl:
    """In-memory SourceControlPort double for workspace tests."""

    def __init__(self, revision: str = "abc") -> None:
        self._revision = revision
        self.cloned: list[Repository] = []
        self.branches: list[tuple[Repository, str, str]] = []
        self.worktrees: list[tuple[Repository, str, str, str]] = []

    async def register_repository(self, repository: Repository) -> None: ...

    async def clone_or_fetch(self, repository: Repository) -> None:
        self.cloned.append(repository)

    async def get_default_branch(self, repository: Repository) -> str:
        return "main"

    async def get_current_revision(self, repository: Repository) -> str:
        return self._revision

    async def list_changed_files(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> list[str]:
        return []

    async def read_file_at_revision(
        self, repository: Repository, path: str, revision: str
    ) -> bytes:
        return b""

    async def create_branch(
        self, repository: Repository, branch_name: str, base_revision: str
    ) -> None:
        self.branches.append((repository, branch_name, base_revision))

    async def create_worktree(
        self,
        repository: Repository,
        branch_name: str,
        base_revision: str,
        path: str,
    ) -> None:
        self.worktrees.append((repository, branch_name, base_revision, path))

    async def get_diff(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> str:
        return ""

    async def commit(self, repository: Repository, branch_name: str, message: str) -> str:
        return "newsha"

    async def push(self, repository: Repository, branch_name: str) -> None: ...


def _descriptor(name: str = "fake", **caps: bool | int) -> ExecutorDescriptor:
    return ExecutorDescriptor(
        name=name,
        kind=ExecutorKind.FAKE,
        capabilities=ExecutorCapabilities(**caps),  # type: ignore[arg-type]
        metadata=dict(caps),
    )


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=new_execution_id(),
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=new_work_item_id(),
        repository_ref="git@example:auth.git",
        base_revision="abc",
    )


async def test_executor_registry_select_coding() -> None:
    registry = InMemoryExecutorRegistry()
    await registry.register(_descriptor("non", coding=False, context_window=8000))
    await registry.register(_descriptor("coder", coding=True, context_window=32000))
    selected = await registry.select(requires_coding=True)
    assert selected is not None
    assert selected.name == "coder"


async def test_model_capability_profile_to_capabilities() -> None:
    profile = ModelCapabilityProfile(
        name="claude", context_window=200000, deployment=ModelDeployment.REMOTE
    )
    capabilities = profile.to_capabilities()
    assert capabilities.context_window == 200000
    assert capabilities.coding is True


async def test_workspace_manager_creates_workspace() -> None:
    source_control = _FakeSourceControl(revision="abc")
    manager = WorkspaceManager(source_control=source_control, workspace_root="/tmp/ws")
    project = Project(name="auth")
    repository = Repository(project_id=project.id, name="auth", clone_url="git@example:auth.git")
    workspace = await manager.create_workspace(repository)
    assert workspace.base_revision == "abc"
    assert workspace.branch_name.startswith("brain/")
    assert source_control.branches  # create_branch called
    assert source_control.worktrees  # create_worktree called
    assert source_control.cloned  # clone_or_fetch called
    await manager.cleanup_workspace(workspace)


async def test_execution_request_builder() -> None:
    project = Project(name="auth")
    work_item = WorkItem(project_id=project.id, title="Implement login")
    repository = Repository(project_id=project.id, name="auth", clone_url="git@example:auth.git")
    workspace = Workspace(
        workspace_id=uuid.uuid4(),
        repository=repository,
        branch_name="brain/task/abc",
        path="/tmp/ws/abc",
        base_revision="abc",
    )
    executor = _descriptor(name="fake", git_commit=True)
    builder = ExecutionRequestBuilder()
    built = await builder.build(
        project=project,
        work_item=work_item,
        repository=repository,
        workspace=workspace,
        executor=executor,
    )
    request = built.request
    assert request.work_item_id == work_item.id
    assert request.base_revision == "abc"
    assert request.repository_ref == "git@example:auth.git"
    assert request.permissions.git_commit is True


async def test_fake_executor_returns_structured_result() -> None:
    executor = FakeExecutor(modified_files=["app/login.py"])
    request = _request()
    result = await executor.execute(request)
    assert isinstance(executor, ExecutorPort)
    assert result.execution_id == request.execution_id
    assert result.status == ExecutionStatus.COMPLETED
    assert result.modified_files == ["app/login.py"]
    assert result.diff is not None
    assert executor.received_requests == [request]


async def test_pi_executor_placeholder_round_trip() -> None:
    executor = PiExecutor()
    request = _request()
    result = await executor.execute(request)
    assert result.execution_id == request.execution_id
    assert result.status == ExecutionStatus.COMPLETED


async def test_pi_executor_with_custom_transport() -> None:
    class _StubTransport:
        async def round_trip(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "status": "completed",
                "modified_files": ["app/x.py"],
                "tests_executed": ["test_x"],
            }

    executor = PiExecutor(transport=_StubTransport())
    request = _request()
    result = await executor.execute(request)
    assert result.modified_files == ["app/x.py"]
    assert result.tests_executed == ["test_x"]


def _brain_tools() -> BrainTools:
    work_items = InMemoryWorkItemRepository()
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    graph = InMemoryKnowledgeGraph()
    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    jit = JustInTimeRetrieval(
        code_graph=InMemoryCodeGraphRepository(),
        requirements=InMemoryRequirementRepository(),
        decisions=InMemoryDecisionRepository(),
        retrieval=retrieval,
    )
    return BrainTools(work_items=work_items, jit=jit)


async def test_brain_tools_task_and_permissions() -> None:
    tools = _brain_tools()
    work_item = WorkItem(project_id=new_project_id(), title="Task")
    await tools._work_items.create(work_item)

    task = await tools.brain_get_task(work_item.id)
    assert task is not None
    assert task.title == "Task"

    # Permission enforcement: only allowed tools are exposed.
    allowed = tools.allowed_tools(["brain_get_task", "brain_get_symbol_context", "evil_tool"])
    assert "evil_tool" not in allowed
    assert "brain_get_task" in allowed
    assert set(allowed) <= TOOL_REGISTRY


async def test_brain_tools_find_related() -> None:
    tools = _brain_tools()
    repository_id = RepositoryId(uuid.uuid4())
    symbols = await tools._jit.find_related_files(repository_id, "abc", "nope")
    assert symbols == []
