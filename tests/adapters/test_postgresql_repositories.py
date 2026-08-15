"""Run every repository contract against the PostgreSQL implementations.

These are the same contract suites already used by the in-memory reference
adapters, proving that the two adapters are interchangeable behind the ports.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from brain.adapters.postgresql.database import PostgresRepositories, create_repositories
from brain.adapters.postgresql.repositories import (
    PostgresActorRepository,
    PostgresArtifactRepository,
    PostgresDecisionRepository,
    PostgresEvidenceRepository,
    PostgresRepositoryRepository,
    PostgresVerificationResultRepository,
)
from brain.adapters.postgresql.tables import ExternalReferenceRow
from brain.domain.actors import Actor, ActorType
from brain.domain.artifacts import Artifact, ArtifactType
from brain.domain.decisions import Decision
from brain.domain.evidence import Evidence, EvidenceType
from brain.domain.executions import Execution
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    ExecutionId,
    new_workflow_id,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.verification import VerificationResult, VerificationVerdict
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
def repositories(postgres_session: AsyncSession) -> PostgresRepositories:
    return create_repositories(postgres_session)


class TestPostgresProjectRepository(ProjectRepositoryContract):
    @pytest.fixture
    def project_repository(self, postgres_session: AsyncSession) -> ProjectRepository:
        return create_repositories(postgres_session).projects


class TestPostgresWorkItemRepository(WorkItemRepositoryContract):
    @pytest.fixture
    def work_item_repository(self, postgres_session: AsyncSession) -> WorkItemRepository:
        return create_repositories(postgres_session).work_items


class TestPostgresRequirementRepository(RequirementRepositoryContract):
    @pytest.fixture
    def requirement_repository(self, postgres_session: AsyncSession) -> RequirementRepository:
        return create_repositories(postgres_session).requirements


class TestPostgresDocumentRepository(DocumentRepositoryContract):
    @pytest.fixture
    def document_repository(self, postgres_session: AsyncSession) -> DocumentRepository:
        return create_repositories(postgres_session).documents


class TestPostgresExecutionRepository(ExecutionRepositoryContract):
    @pytest.fixture
    def execution_repository(self, postgres_session: AsyncSession) -> ExecutionRepository:
        return create_repositories(postgres_session).executions


class TestPostgresSoftwareCatalogRepository(SoftwareCatalogRepositoryContract):
    @pytest.fixture
    def catalog_repository(self, postgres_session: AsyncSession) -> SoftwareCatalogRepository:
        return create_repositories(postgres_session).software_catalog


class TestPostgresCodeGraphRepository(CodeGraphRepositoryContract):
    @pytest.fixture
    def code_graph_repository(self, postgres_session: AsyncSession) -> CodeGraphRepository:
        return create_repositories(postgres_session).code_graph


async def test_actor_repository_round_trip(postgres_session: AsyncSession) -> None:
    repo: ActorRepository = PostgresActorRepository(postgres_session)
    created = await repo.create(Actor(actor_type=ActorType.HUMAN, display_name="dev"))
    stored = await repo.get(created.id)
    assert stored is not None
    assert stored.display_name == "dev"
    assert await repo.list() == [created]
    await repo.delete(created.id)
    assert await repo.list() == []


async def test_repository_repository_round_trip(
    repositories: PostgresRepositories, postgres_session: AsyncSession
) -> None:
    repo: RepositoryRepository = PostgresRepositoryRepository(postgres_session)
    proj = Project(name="auth")
    await repositories.projects.create(proj)
    created = await repo.create(
        Repository(project_id=proj.id, name="auth-service", clone_url="git@example:auth.git")
    )
    stored = await repo.get(created.id)
    assert stored is not None
    assert stored.clone_url == "git@example:auth.git"
    assert [r.id for r in await repo.list_by_project(proj.id)] == [created.id]


async def test_decision_repository_round_trip(
    repositories: PostgresRepositories, postgres_session: AsyncSession
) -> None:
    repo: DecisionRepository = PostgresDecisionRepository(postgres_session)
    proj = Project(name="auth")
    await repositories.projects.create(proj)
    created = await repo.create(Decision(project_id=proj.id, title="Use JWT"))
    stored = await repo.get(created.id)
    assert stored is not None
    assert stored.title == "Use JWT"
    assert [d.id for d in await repo.list_by_project(proj.id)] == [created.id]


async def test_evidence_repository_round_trip(postgres_session: AsyncSession) -> None:
    repo: EvidenceRepository = PostgresEvidenceRepository(postgres_session)
    executor = Actor(actor_type=ActorType.AGENT, display_name="pi")
    work_item = WorkItem(project_id=Project(name="auth").id, title="t")
    execution = Execution(
        workflow_id=new_workflow_id(), work_item_id=work_item.id, executor_id=executor.id
    )
    evidence = await repo.create(
        Evidence(
            execution_id=execution.id,
            evidence_type=EvidenceType.GIT_DIFF,
            source="diff --git ...",
        )
    )
    stored = await repo.get(evidence.id)
    assert stored is not None
    assert stored.source == "diff --git ..."
    assert [e.id for e in await repo.list_by_execution(execution.id)] == [evidence.id]


async def test_artifact_repository_round_trip(postgres_session: AsyncSession) -> None:
    repo: ArtifactRepository = PostgresArtifactRepository(postgres_session)
    project_id = Project(name="auth").id
    created = await repo.create(
        Artifact(project_id=project_id, artifact_type=ArtifactType.DIFF, uri="s3://x/patch.diff")
    )
    stored = await repo.get(created.id)
    assert stored is not None
    assert stored.uri == "s3://x/patch.diff"
    assert [a.id for a in await repo.list_by_project(project_id)] == [created.id]


async def test_verification_result_repository_round_trip(postgres_session: AsyncSession) -> None:
    repo: VerificationResultRepository = PostgresVerificationResultRepository(postgres_session)
    execution_id = ExecutionId(Project(name="x").id)
    created = await repo.create(
        VerificationResult(execution_id=execution_id, verdict=VerificationVerdict.PASS)
    )
    stored = await repo.get(created.id)
    assert stored is not None
    assert stored.verdict == VerificationVerdict.PASS
    assert [v.id for v in await repo.list_by_execution(execution_id)] == [created.id]


async def test_external_references_are_persisted_to_index_table(
    repositories: PostgresRepositories, postgres_session: AsyncSession
) -> None:
    project = Project(
        name="auth",
        external_refs=[
            ExternalReference(provider="jira", external_id="AUTH-42", url="https://jira/AUTH-42")
        ],
    )
    await repositories.projects.create(project)

    rows = (
        (
            await postgres_session.execute(
                select(ExternalReferenceRow).where(ExternalReferenceRow.owner_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].provider == "jira"
    assert rows[0].external_id == "AUTH-42"
    assert rows[0].owner_type == "project"


async def test_external_references_are_updated_in_place(
    repositories: PostgresRepositories, postgres_session: AsyncSession
) -> None:
    project = Project(
        name="auth",
        external_refs=[ExternalReference(provider="jira", external_id="AUTH-42")],
    )
    await repositories.projects.create(project)
    project.external_refs = [ExternalReference(provider="openproject", external_id="2148")]
    await repositories.projects.update(project)

    rows = (
        (
            await postgres_session.execute(
                select(ExternalReferenceRow).where(ExternalReferenceRow.owner_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].provider == "openproject"
