"""Phase 12 golden tests and completion gate.

The brain can execute a WorkItem through an executor (Pi behind ``ExecutorPort``,
or the deterministic fake for offline runs) using a bounded context capsule and
collect a structured result -- without the core depending on any Pi session
model.
"""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.executors.pi import PiExecutor
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
from brain.adapters.in_memory.executor_registry import InMemoryExecutorRegistry
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryExecutionRepository,
    InMemoryRequirementRepository,
    InMemoryVerificationResultRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.application.brain_tools import BrainTools
from brain.application.context_engine import ContextEngineService
from brain.application.execution_request_builder import ExecutionRequestBuilder
from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.jit_retrieval import JustInTimeRetrieval
from brain.application.token_estimation import TokenEstimator
from brain.application.workspace_manager import Workspace, WorkspaceManager
from brain.domain.context import ContextRequest, ContextType
from brain.domain.executions import ExecutionStatus
from brain.domain.executor import (
    ExecutorCapabilities,
    ExecutorDescriptor,
    ExecutorKind,
    ModelDeployment,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.work_items import WorkItem


class _FakeSourceControl:
    def __init__(self, revision: str = "abc") -> None:
        self._revision = revision

    async def register_repository(self, repository: Repository) -> None: ...

    async def clone_or_fetch(self, repository: Repository) -> None: ...

    async def get_default_branch(self, repository: Repository) -> str:
        return "main"

    async def get_current_revision(self, repository: Repository) -> str:
        return self._revision

    async def list_changed_files(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> list[str]:
        return ["app/login.py"]

    async def read_file_at_revision(
        self, repository: Repository, path: str, revision: str
    ) -> bytes:
        return b""

    async def create_branch(
        self, repository: Repository, branch_name: str, base_revision: str
    ) -> None: ...

    async def create_worktree(
        self,
        repository: Repository,
        branch_name: str,
        base_revision: str,
        path: str,
    ) -> None: ...

    async def get_diff(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> str:
        return "diff --git a/app/login.py b/app/login.py"

    async def commit(self, repository: Repository, branch_name: str, message: str) -> str:
        return "newsha"

    async def push(self, repository: Repository, branch_name: str) -> None: ...


def _pi_descriptor() -> ExecutorDescriptor:
    return ExecutorDescriptor(
        name="pi",
        kind=ExecutorKind.PI,
        capabilities=ExecutorCapabilities(
            coding=True,
            tool_support=True,
            context_window=128000,
            preferred_context_budget=8000,
            deployment=ModelDeployment.REMOTE,
            supported_tools=[
                "brain_get_task",
                "brain_get_symbol_context",
                "brain_find_related_files",
                "brain_find_related_tests",
                "brain_get_requirement",
                "brain_get_decisions",
                "brain_request_more_context",
            ],
        ),
        supports_structured_tools=True,
    )


@pytest.fixture
def project() -> Project:
    return Project(name="auth")


@pytest.fixture
def work_item(project: Project) -> WorkItem:
    return WorkItem(project_id=project.id, title="Implement login")


async def test_gate_selects_pi_executor() -> None:
    registry = InMemoryExecutorRegistry()
    await registry.register(_pi_descriptor())
    selected = await registry.select(requires_coding=True, requires_tools=True)
    assert selected is not None
    assert selected.name == "pi"
    assert "brain_get_task" in selected.capabilities.supported_tools


async def test_gate_builds_bounded_context_capsule(project: Project, work_item: WorkItem) -> None:
    work_items = InMemoryWorkItemRepository()
    await work_items.create(work_item)
    engine = ContextEngineService(
        work_items=work_items,
        requirements=InMemoryRequirementRepository(),
        executions=InMemoryExecutionRepository(),
        verification_results=InMemoryVerificationResultRepository(),
        code_graph=InMemoryCodeGraphRepository(),
        knowledge_graph=InMemoryKnowledgeGraph(),
        retrieval=HybridRetrievalService(
            index=InMemorySemanticIndex(embeddings=HashEmbeddingService()),
            embeddings=HashEmbeddingService(),
            graph=InMemoryKnowledgeGraph(),
        ),
        capsules=InMemoryContextCapsuleRepository(),
        token_estimator=TokenEstimator(),
    )
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        context_type=ContextType.CODING,
        preferred_token_budget=8000,
    )
    result = await engine.build(request)
    assert result.capsule.is_within_budget
    assert result.capsule.total_tokens <= result.capsule.model_budget_tokens


async def test_gate_builds_execution_request_with_capsule(
    project: Project, work_item: WorkItem
) -> None:
    repository = Repository(project_id=project.id, name="auth", clone_url="git@example:auth.git")
    workspace = Workspace(
        workspace_id=uuid.uuid4(),
        repository=repository,
        branch_name="brain/task/abc",
        path="/tmp/ws/abc",
        base_revision="abc",
    )
    builder = ExecutionRequestBuilder()
    built = await builder.build(
        project=project,
        work_item=work_item,
        repository=repository,
        workspace=workspace,
        executor=_pi_descriptor(),
    )
    assert built.request.work_item_id == work_item.id
    assert built.request.base_revision == "abc"
    assert built.request.permissions.repository_read is True


async def test_gate_executes_through_pi_and_collects_result(
    project: Project, work_item: WorkItem
) -> None:
    repository = Repository(project_id=project.id, name="auth", clone_url="git@example:auth.git")
    workspace = Workspace(
        workspace_id=uuid.uuid4(),
        repository=repository,
        branch_name="brain/task/abc",
        path="/tmp/ws/abc",
        base_revision="abc",
    )
    builder = ExecutionRequestBuilder()
    built = await builder.build(
        project=project,
        work_item=work_item,
        repository=repository,
        workspace=workspace,
        executor=_pi_descriptor(),
    )
    executor = PiExecutor()
    result = await executor.execute(built.request)
    assert result.execution_id == built.request.execution_id
    assert result.status == ExecutionStatus.COMPLETED


async def test_gate_brain_tools_available_to_pi(project: Project, work_item: WorkItem) -> None:
    work_items = InMemoryWorkItemRepository()
    await work_items.create(work_item)
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    graph = InMemoryKnowledgeGraph()
    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    jit = JustInTimeRetrieval(
        code_graph=InMemoryCodeGraphRepository(),
        requirements=InMemoryRequirementRepository(),
        decisions=InMemoryDecisionRepository(),
        retrieval=retrieval,
    )
    tools = BrainTools(work_items=work_items, jit=jit)
    descriptor = _pi_descriptor()
    allowed = tools.allowed_tools(descriptor.capabilities.supported_tools)
    assert "brain_get_task" in allowed
    assert "brain_get_symbol_context" in allowed
    task = await tools.brain_get_task(work_item.id)
    assert task is not None
    assert task.title == "Implement login"


async def test_gate_workspace_manager_creates_isolated_workspace(
    project: Project,
) -> None:
    source_control = _FakeSourceControl(revision="abc")
    manager = WorkspaceManager(source_control=source_control, workspace_root="/tmp/ws")
    repository = Repository(project_id=project.id, name="auth", clone_url="git@example:auth.git")
    workspace = await manager.create_workspace(repository)
    assert workspace.branch_name.startswith("brain/")
    assert workspace.base_revision == "abc"
    await manager.cleanup_workspace(workspace)
