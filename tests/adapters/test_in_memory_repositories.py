"""Run every repository contract against the in-memory reference adapters."""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.repositories import (
    InMemoryActorRepository,
    InMemoryArtifactRepository,
    InMemoryDecisionRepository,
    InMemoryDocumentRepository,
    InMemoryEvidenceRepository,
    InMemoryExecutionRepository,
    InMemoryProjectRepository,
    InMemoryRepositoryRepository,
    InMemoryRequirementRepository,
    InMemorySoftwareCatalogRepository,
    InMemoryVerificationResultRepository,
    InMemoryWorkItemRepository,
)
from brain.domain.actors import Actor
from brain.domain.artifacts import Artifact
from brain.domain.decisions import Decision
from brain.domain.evidence import Evidence
from brain.domain.executions import Execution
from brain.domain.identity import new_workflow_id
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.verification import VerificationResult
from brain.domain.work_items import WorkItem
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.repositories import (
    ActorRepository,
    ArtifactRepository,
    DecisionRepository,
    DocumentRepository,
    EvidenceRepository,
    ExecutionRepository,
    ProjectRepository,
    RepositoryRepository,
    RequirementRepository,
    VerificationResultRepository,
    WorkItemRepository,
)
from brain.ports.topology import SoftwareCatalogRepository
from tests.contracts.code_graph import CodeGraphRepositoryContract
from tests.contracts.document_repository import DocumentRepositoryContract
from tests.contracts.execution_repository import ExecutionRepositoryContract
from tests.contracts.project_repository import ProjectRepositoryContract
from tests.contracts.requirement_repository import RequirementRepositoryContract
from tests.contracts.software_catalog import SoftwareCatalogRepositoryContract
from tests.contracts.work_item_repository import WorkItemRepositoryContract


@pytest.fixture
def project_repository() -> ProjectRepository:
    return InMemoryProjectRepository()


class TestInMemoryProjectRepository(ProjectRepositoryContract):
    @pytest.fixture
    def project_repository(self) -> ProjectRepository:
        return InMemoryProjectRepository()


class TestInMemoryWorkItemRepository(WorkItemRepositoryContract):
    @pytest.fixture
    def work_item_repository(self) -> WorkItemRepository:
        return InMemoryWorkItemRepository()


class TestInMemoryRequirementRepository(RequirementRepositoryContract):
    @pytest.fixture
    def requirement_repository(self) -> RequirementRepository:
        return InMemoryRequirementRepository()


class TestInMemoryDocumentRepository(DocumentRepositoryContract):
    @pytest.fixture
    def document_repository(self) -> DocumentRepository:
        return InMemoryDocumentRepository()


class TestInMemoryExecutionRepository(ExecutionRepositoryContract):
    @pytest.fixture
    def execution_repository(self) -> ExecutionRepository:
        return InMemoryExecutionRepository()


class TestInMemorySoftwareCatalogRepository(SoftwareCatalogRepositoryContract):
    @pytest.fixture
    def catalog_repository(self) -> SoftwareCatalogRepository:
        return InMemorySoftwareCatalogRepository()


class TestInMemoryCodeGraphRepository(CodeGraphRepositoryContract):
    @pytest.fixture
    def code_graph_repository(self) -> CodeGraphRepository:
        return InMemoryCodeGraphRepository()


async def test_actor_repository_round_trip() -> None:
    repo: ActorRepository = InMemoryActorRepository()
    created = await repo.create(Actor(actor_type="human", display_name="dev"))
    assert (await repo.get(created.id)).display_name == "dev"
    assert await repo.list() == [created]
    await repo.delete(created.id)
    assert await repo.list() == []


async def test_repository_repository_round_trip(project_repository: ProjectRepository) -> None:
    repo: RepositoryRepository = InMemoryRepositoryRepository()
    proj = Project(name="auth")
    await project_repository.create(proj)
    created = await repo.create(
        Repository(project_id=proj.id, name="auth-service", clone_url="git@example:auth.git")
    )
    stored = await repo.get(created.id)
    assert stored is not None
    assert stored.clone_url == "git@example:auth.git"
    assert [r.id for r in await repo.list_by_project(proj.id)] == [created.id]


async def test_decision_repository_round_trip(project_repository: ProjectRepository) -> None:
    repo: DecisionRepository = InMemoryDecisionRepository()
    proj = Project(name="auth")
    await project_repository.create(proj)
    created = await repo.create(Decision(project_id=proj.id, title="Use JWT"))
    assert (await repo.get(created.id)).title == "Use JWT"
    assert [d.id for d in await repo.list_by_project(proj.id)] == [created.id]


async def test_evidence_repository_round_trip() -> None:
    repo: EvidenceRepository = InMemoryEvidenceRepository()
    executor = Actor(actor_type="agent", display_name="pi")
    work_item = WorkItem(project_id=uuid.uuid4(), title="t")
    execution = Execution(
        workflow_id=new_workflow_id(), work_item_id=work_item.id, executor_id=executor.id
    )
    evidence = await repo.create(
        Evidence(execution_id=execution.id, evidence_type="git_diff", source="diff --git ...")
    )
    assert (await repo.get(evidence.id)).source == "diff --git ..."
    assert [e.id for e in await repo.list_by_execution(execution.id)] == [evidence.id]


async def test_artifact_repository_round_trip() -> None:
    repo: ArtifactRepository = InMemoryArtifactRepository()
    project_id = Project(name="auth").id
    created = await repo.create(
        Artifact(project_id=project_id, artifact_type="diff", uri="s3://x/patch.diff")
    )
    assert (await repo.get(created.id)).uri == "s3://x/patch.diff"
    assert [a.id for a in await repo.list_by_project(project_id)] == [created.id]


async def test_verification_result_repository_round_trip() -> None:
    repo: VerificationResultRepository = InMemoryVerificationResultRepository()
    execution_id = uuid.uuid4()
    created = await repo.create(VerificationResult(execution_id=execution_id, verdict="pass"))
    assert (await repo.get(created.id)).verdict == "pass"
    assert [v.id for v in await repo.list_by_execution(execution_id)] == [created.id]
