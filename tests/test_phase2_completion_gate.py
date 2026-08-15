"""Phase 2 completion gate: restart safety.

The gate for Phase 2 is that every canonical transactional entity written
through the Unit of Work survives a process restart.  We simulate a restart
by writing with one engine/session, then reading everything back with a
brand-new engine and session.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from brain.adapters.postgresql.config import DatabaseSettings
from brain.adapters.postgresql.database import (
    async_session_factory,
    create_async_engine,
    create_repositories,
)
from brain.adapters.postgresql.tables import (
    ActorRow,
    ArtifactRow,
    Base,
    DecisionRow,
    DocumentNodeRow,
    DocumentRow,
    DocumentVersionRow,
    EvidenceRow,
    ExecutionRow,
    ExternalReferenceRow,
    ProjectRow,
    RepositoryRow,
    RequirementRow,
    VerificationResultRow,
    WorkItemRow,
)
from brain.adapters.postgresql.unit_of_work import PostgresUnitOfWork
from brain.domain import (
    Actor,
    ActorType,
    Artifact,
    ArtifactType,
    Decision,
    Document,
    DocumentNode,
    DocumentSource,
    DocumentType,
    DocumentVersion,
    Evidence,
    EvidenceType,
    Execution,
    ExternalReference,
    Project,
    ProjectStatus,
    Repository,
    Requirement,
    SourceReference,
    VerificationResult,
    VerificationVerdict,
    WorkItem,
)
from brain.domain.identity import WorkflowId
from tests.conftest import TEST_DATABASE_URL, postgres_reachable


@pytest.fixture
def gate_settings() -> DatabaseSettings:
    return DatabaseSettings(url=TEST_DATABASE_URL, echo=False)


async def test_canonical_state_survives_restart(gate_settings: DatabaseSettings) -> None:
    if not postgres_reachable(gate_settings.url):
        pytest.skip("PostgreSQL is not available; start it with: docker compose up -d")

    project = Project(
        name="gate",
        status=ProjectStatus.ACTIVE,
        external_refs=[ExternalReference(provider="jira", external_id="GATE-1")],
    )
    repository = Repository(
        project_id=project.id,
        name="gate-svc",
        clone_url="git@example:gate.git",
        current_revision="a1b2c3",
    )
    actor = Actor(actor_type=ActorType.AGENT, display_name="gate-agent", capabilities=["code"])
    requirement = Requirement(project_id=project.id, key="GATE-REQ", title="gate req")
    work_item = WorkItem(
        project_id=project.id,
        title="gate work item",
        requirement_refs=[requirement.id],
        external_refs=[ExternalReference(provider="gitlab", external_id="!1")],
    )
    document = Document(
        project_id=project.id,
        type=DocumentType.README,
        title="gate doc",
        source=DocumentSource(provider="git", uri="README.md"),
    )
    version = DocumentVersion(document_id=document.id, checksum="deadbeef", commit_sha="a1b2c3")
    node = DocumentNode(version_id=version.id, title="Root", heading_path=["Root"])
    decision = Decision(
        project_id=project.id,
        title="gate decision",
        source_refs=[SourceReference(provider="manual", reference="manual", url=None)],
        external_refs=[ExternalReference(provider="jira", external_id="GATE-2")],
    )
    execution = Execution(
        workflow_id=WorkflowId(uuid.uuid4()), work_item_id=work_item.id, executor_id=actor.id
    )
    artifact = Artifact(project_id=project.id, artifact_type=ArtifactType.DIFF, commit_sha="a1b2c3")
    evidence = Evidence(
        execution_id=execution.id, evidence_type=EvidenceType.TEST_RESULT, source="pytest"
    )
    verification = VerificationResult(
        execution_id=execution.id,
        verdict=VerificationVerdict.PASS,
        evidence_refs=[evidence.id],
    )

    write_engine = create_async_engine(gate_settings)
    write_factory = async_session_factory(write_engine)
    try:
        async with write_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with PostgresUnitOfWork(write_factory) as uow:
            await uow.repos.projects.create(project)
            await uow.repos.repositories.create(repository)
            await uow.repos.actors.create(actor)
            await uow.repos.requirements.create(requirement)
            await uow.repos.work_items.create(work_item)
            await uow.repos.documents.create(document)
            await uow.repos.documents.add_version(version)
            await uow.repos.documents.add_node(node)
            await uow.repos.decisions.create(decision)
            await uow.repos.executions.create(execution)
            await uow.repos.artifacts.create(artifact)
            await uow.repos.evidence.create(evidence)
            await uow.repos.verification_results.create(verification)
            await uow.commit()
    finally:
        await write_engine.dispose()

    read_engine = create_async_engine(gate_settings)
    read_factory = async_session_factory(read_engine)
    try:
        async with read_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with read_factory() as session:
            repos = create_repositories(session)
            assert await repos.projects.get(project.id) == project
            assert await repos.repositories.get(repository.id) == repository
            assert await repos.actors.get(actor.id) == actor
            assert await repos.requirements.get(requirement.id) == requirement
            assert await repos.work_items.get(work_item.id) == work_item
            assert await repos.documents.get(document.id) == document
            assert await repos.documents.get_version(version.id) == version
            assert await repos.documents.list_nodes(version.id) == [node]
            assert await repos.decisions.get(decision.id) == decision
            assert await repos.executions.get(execution.id) == execution
            assert await repos.artifacts.get(artifact.id) == artifact
            assert await repos.evidence.get(evidence.id) == evidence
            assert await repos.verification_results.get(verification.id) == verification
    finally:
        await read_engine.dispose()

    async def _cleanup(session: AsyncSession) -> None:
        owner_ids = [project.id, work_item.id, decision.id, document.id]
        await session.execute(
            delete(ExternalReferenceRow).where(ExternalReferenceRow.owner_id.in_(owner_ids))
        )
        await session.execute(
            delete(DocumentNodeRow).where(DocumentNodeRow.version_id == version.id)
        )
        await session.execute(delete(DocumentVersionRow).where(DocumentVersionRow.id == version.id))
        await session.execute(
            delete(VerificationResultRow).where(VerificationResultRow.id == verification.id)
        )
        await session.execute(delete(EvidenceRow).where(EvidenceRow.id == evidence.id))
        await session.execute(delete(ArtifactRow).where(ArtifactRow.id == artifact.id))
        await session.execute(delete(ExecutionRow).where(ExecutionRow.id == execution.id))
        await session.execute(delete(DecisionRow).where(DecisionRow.id == decision.id))
        await session.execute(delete(DocumentRow).where(DocumentRow.id == document.id))
        await session.execute(delete(WorkItemRow).where(WorkItemRow.id == work_item.id))
        await session.execute(delete(RequirementRow).where(RequirementRow.id == requirement.id))
        await session.execute(delete(ActorRow).where(ActorRow.id == actor.id))
        await session.execute(delete(RepositoryRow).where(RepositoryRow.id == repository.id))
        await session.execute(delete(ProjectRow).where(ProjectRow.id == project.id))
        await session.commit()

    cleanup_engine = create_async_engine(gate_settings)
    cleanup_factory = async_session_factory(cleanup_engine)
    try:
        async with cleanup_factory() as session:
            await _cleanup(session)
    finally:
        await cleanup_engine.dispose()
