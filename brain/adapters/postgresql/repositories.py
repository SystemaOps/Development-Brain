"""PostgreSQL implementations of the state repository ports.

Every repository is bound to one :class:`sqlalchemy.ext.asyncio.AsyncSession`.
Writes ``flush()`` so rows are visible to later queries in the same session;
committing/rolling back is the caller's responsibility (use
:class:`~brain.adapters.postgresql.unit_of_work.PostgresUnitOfWork` for atomic
multi-repository writes).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from brain.adapters.postgresql.serialization import dump_models, dump_uuids
from brain.adapters.postgresql.tables import (
    ActorRow,
    ArtifactRow,
    DecisionRow,
    DocumentNodeRow,
    DocumentRow,
    DocumentVersionRow,
    EventLogRow,
    EvidenceRow,
    ExecutionRow,
    ExternalReferenceRow,
    IdempotencyKeyRow,
    ProjectRow,
    RepositoryChangeSetRow,
    RepositoryRow,
    RepositorySnapshotRow,
    RequirementRow,
    VerificationResultRow,
    WorkItemRow,
)
from brain.domain.actors import Actor
from brain.domain.artifacts import Artifact
from brain.domain.decisions import Decision
from brain.domain.documents import Document, DocumentNode, DocumentVersion
from brain.domain.events import EventEnvelope
from brain.domain.evidence import Evidence
from brain.domain.executions import Execution
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    ActorId,
    ArtifactId,
    DecisionId,
    DocumentId,
    DocumentVersionId,
    EvidenceId,
    ExecutionId,
    ProjectId,
    RepositoryId,
    RequirementId,
    VerificationId,
    WorkItemId,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.repository_scan import (
    ChangedFile,
    FileCategory,
    RepositoryChangeSet,
    RepositorySnapshot,
)
from brain.domain.requirements import Requirement
from brain.domain.verification import VerificationResult
from brain.domain.work_items import WorkItem


def _as_str(value: object) -> str:
    """String form of an enum member or a plain string.

    The domain contracts allow callers to assign raw ``str`` values to enum
    fields (Pydantic does not coerce on assignment), so serialization must
    tolerate both.
    """
    if isinstance(value, str):
        return value
    return getattr(value, "value", str(value))


class _PostgresRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _replace_external_refs(
        self, owner_type: str, owner_id: uuid.UUID, refs: list[ExternalReference]
    ) -> None:
        await self._session.execute(
            delete(ExternalReferenceRow).where(
                ExternalReferenceRow.owner_type == owner_type,
                ExternalReferenceRow.owner_id == owner_id,
            )
        )
        for ref in refs:
            self._session.add(
                ExternalReferenceRow(
                    id=uuid.uuid4(),
                    owner_type=owner_type,
                    owner_id=owner_id,
                    provider=ref.provider,
                    external_id=ref.external_id,
                    external_type=ref.external_type,
                    url=ref.url,
                    namespace=ref.namespace,
                )
            )

    async def _delete_external_refs(self, owner_type: str, owner_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(ExternalReferenceRow).where(
                ExternalReferenceRow.owner_type == owner_type,
                ExternalReferenceRow.owner_id == owner_id,
            )
        )


class PostgresProjectRepository(_PostgresRepository):
    async def create(self, project: Project) -> Project:
        self._session.add(
            ProjectRow(
                id=project.id,
                name=project.name,
                description=project.description,
                status=_as_str(project.status),
                repositories=dump_uuids(project.repositories),
                external_refs=dump_models(project.external_refs),
            )
        )
        await self._replace_external_refs("project", project.id, project.external_refs)
        await self._session.flush()
        return project

    async def get(self, project_id: ProjectId) -> Project | None:
        row = await self._session.get(ProjectRow, project_id)
        return _project_from_row(row) if row is not None else None

    async def list(self) -> list[Project]:
        result = await self._session.execute(select(ProjectRow).order_by(ProjectRow.name))
        return [_project_from_row(row) for row in result.scalars().all()]

    async def update(self, project: Project) -> Project:
        row = await self._session.get(ProjectRow, project.id)
        if row is None:
            return await self.create(project)
        row.name = project.name
        row.description = project.description
        row.status = _as_str(project.status)
        row.repositories = dump_uuids(project.repositories)
        row.external_refs = dump_models(project.external_refs)
        await self._replace_external_refs("project", project.id, project.external_refs)
        await self._session.flush()
        return project

    async def delete(self, project_id: ProjectId) -> None:
        row = await self._session.get(ProjectRow, project_id)
        if row is not None:
            await self._session.delete(row)
            await self._delete_external_refs("project", project_id)
            await self._session.flush()


class PostgresRepositoryRepository(_PostgresRepository):
    async def create(self, repository: Repository) -> Repository:
        self._session.add(
            RepositoryRow(
                id=repository.id,
                project_id=repository.project_id,
                name=repository.name,
                clone_url=repository.clone_url,
                default_branch=repository.default_branch,
                current_revision=repository.current_revision,
                external_refs=dump_models(repository.external_refs),
            )
        )
        await self._replace_external_refs("repository", repository.id, repository.external_refs)
        await self._session.flush()
        return repository

    async def get(self, repository_id: RepositoryId) -> Repository | None:
        row = await self._session.get(RepositoryRow, repository_id)
        return _repository_from_row(row) if row is not None else None

    async def list_by_project(self, project_id: ProjectId) -> list[Repository]:
        result = await self._session.execute(
            select(RepositoryRow)
            .where(RepositoryRow.project_id == project_id)
            .order_by(RepositoryRow.name)
        )
        return [_repository_from_row(row) for row in result.scalars().all()]

    async def update(self, repository: Repository) -> Repository:
        row = await self._session.get(RepositoryRow, repository.id)
        if row is None:
            return await self.create(repository)
        row.project_id = repository.project_id
        row.name = repository.name
        row.clone_url = repository.clone_url
        row.default_branch = repository.default_branch
        row.current_revision = repository.current_revision
        row.external_refs = dump_models(repository.external_refs)
        await self._replace_external_refs("repository", repository.id, repository.external_refs)
        await self._session.flush()
        return repository

    async def delete(self, repository_id: RepositoryId) -> None:
        row = await self._session.get(RepositoryRow, repository_id)
        if row is not None:
            await self._session.delete(row)
            await self._delete_external_refs("repository", repository_id)
            await self._session.flush()


class PostgresActorRepository(_PostgresRepository):
    async def create(self, actor: Actor) -> Actor:
        self._session.add(
            ActorRow(
                id=actor.id,
                actor_type=_as_str(actor.actor_type),
                display_name=actor.display_name,
                capabilities=list(actor.capabilities),
            )
        )
        await self._session.flush()
        return actor

    async def get(self, actor_id: ActorId) -> Actor | None:
        row = await self._session.get(ActorRow, actor_id)
        return _actor_from_row(row) if row is not None else None

    async def list(self) -> list[Actor]:
        result = await self._session.execute(select(ActorRow).order_by(ActorRow.display_name))
        return [_actor_from_row(row) for row in result.scalars().all()]

    async def update(self, actor: Actor) -> Actor:
        row = await self._session.get(ActorRow, actor.id)
        if row is None:
            return await self.create(actor)
        row.actor_type = actor.actor_type.value
        row.display_name = actor.display_name
        row.capabilities = list(actor.capabilities)
        await self._session.flush()
        return actor

    async def delete(self, actor_id: ActorId) -> None:
        row = await self._session.get(ActorRow, actor_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()


class PostgresWorkItemRepository(_PostgresRepository):
    async def create(self, work_item: WorkItem) -> WorkItem:
        self._session.add(_work_item_row(work_item))
        await self._replace_external_refs("work_item", work_item.id, work_item.external_refs)
        await self._session.flush()
        return work_item

    async def get(self, work_item_id: WorkItemId) -> WorkItem | None:
        row = await self._session.get(WorkItemRow, work_item_id)
        return _work_item_from_row(row) if row is not None else None

    async def list_by_project(self, project_id: ProjectId) -> list[WorkItem]:
        result = await self._session.execute(
            select(WorkItemRow)
            .where(WorkItemRow.project_id == project_id)
            .order_by(WorkItemRow.title)
        )
        return [_work_item_from_row(row) for row in result.scalars().all()]

    async def list_by_work_item(self, parent_id: WorkItemId) -> list[WorkItem]:
        result = await self._session.execute(
            select(WorkItemRow).where(WorkItemRow.parent_id == parent_id)
        )
        return [_work_item_from_row(row) for row in result.scalars().all()]

    async def update(self, work_item: WorkItem) -> WorkItem:
        row = await self._session.get(WorkItemRow, work_item.id)
        if row is None:
            return await self.create(work_item)
        _apply_work_item(row, work_item)
        await self._replace_external_refs("work_item", work_item.id, work_item.external_refs)
        await self._session.flush()
        return work_item

    async def delete(self, work_item_id: WorkItemId) -> None:
        row = await self._session.get(WorkItemRow, work_item_id)
        if row is not None:
            await self._session.delete(row)
            await self._delete_external_refs("work_item", work_item_id)
            await self._session.flush()


class PostgresRequirementRepository(_PostgresRepository):
    async def create(self, requirement: Requirement) -> Requirement:
        self._session.add(_requirement_row(requirement))
        await self._session.flush()
        return requirement

    async def get(self, requirement_id: RequirementId) -> Requirement | None:
        row = await self._session.get(RequirementRow, requirement_id)
        return _requirement_from_row(row) if row is not None else None

    async def list_by_project(self, project_id: ProjectId) -> list[Requirement]:
        result = await self._session.execute(
            select(RequirementRow)
            .where(RequirementRow.project_id == project_id)
            .order_by(RequirementRow.title)
        )
        return [_requirement_from_row(row) for row in result.scalars().all()]

    async def list_by_parent(self, parent_id: RequirementId) -> list[Requirement]:
        result = await self._session.execute(
            select(RequirementRow).where(RequirementRow.parent_id == parent_id)
        )
        return [_requirement_from_row(row) for row in result.scalars().all()]

    async def update(self, requirement: Requirement) -> Requirement:
        row = await self._session.get(RequirementRow, requirement.id)
        if row is None:
            return await self.create(requirement)
        _apply_requirement(row, requirement)
        await self._session.flush()
        return requirement

    async def delete(self, requirement_id: RequirementId) -> None:
        row = await self._session.get(RequirementRow, requirement_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()


class PostgresDocumentRepository(_PostgresRepository):
    async def create(self, document: Document) -> Document:
        self._session.add(
            DocumentRow(
                id=document.id,
                project_id=document.project_id,
                type=_as_str(document.type),
                title=document.title,
                source=document.source.model_dump(mode="json"),
                current_version_id=document.current_version_id,
                external_refs=dump_models(document.external_refs),
            )
        )
        await self._replace_external_refs("document", document.id, document.external_refs)
        await self._session.flush()
        return document

    async def get(self, document_id: DocumentId) -> Document | None:
        row = await self._session.get(DocumentRow, document_id)
        return _document_from_row(row) if row is not None else None

    async def list_by_project(self, project_id: ProjectId) -> list[Document]:
        result = await self._session.execute(
            select(DocumentRow)
            .where(DocumentRow.project_id == project_id)
            .order_by(DocumentRow.title)
        )
        return [_document_from_row(row) for row in result.scalars().all()]

    async def find_by_source(self, project_id: ProjectId, source_uri: str) -> Document | None:
        result = await self._session.execute(
            select(DocumentRow).where(
                DocumentRow.project_id == project_id,
                DocumentRow.source["uri"].astext == source_uri,
            )
        )
        row = result.scalar_one_or_none()
        return _document_from_row(row) if row is not None else None

    async def update(self, document: Document) -> Document:
        row = await self._session.get(DocumentRow, document.id)
        if row is None:
            return await self.create(document)
        row.project_id = document.project_id
        row.type = document.type.value
        row.title = document.title
        row.source = document.source.model_dump(mode="json")
        row.current_version_id = document.current_version_id
        row.external_refs = dump_models(document.external_refs)
        await self._replace_external_refs("document", document.id, document.external_refs)
        await self._session.flush()
        return document

    async def delete(self, document_id: DocumentId) -> None:
        row = await self._session.get(DocumentRow, document_id)
        if row is not None:
            await self._session.delete(row)
            await self._delete_external_refs("document", document_id)
            await self._session.flush()

    async def add_version(self, version: DocumentVersion) -> DocumentVersion:
        self._session.add(
            DocumentVersionRow(
                id=version.id,
                document_id=version.document_id,
                source_version=version.source_version,
                repository_id=version.repository_id,
                commit_sha=version.commit_sha,
                checksum=version.checksum,
                ingested_at=version.ingested_at,
                content_uri=version.content_uri,
            )
        )
        await self._session.flush()
        return version

    async def get_version(self, version_id: DocumentVersionId) -> DocumentVersion | None:
        row = await self._session.get(DocumentVersionRow, version_id)
        return _document_version_from_row(row) if row is not None else None

    async def list_versions(self, document_id: DocumentId) -> list[DocumentVersion]:
        result = await self._session.execute(
            select(DocumentVersionRow)
            .where(DocumentVersionRow.document_id == document_id)
            .order_by(DocumentVersionRow.ingested_at)
        )
        return [_document_version_from_row(row) for row in result.scalars().all()]

    async def add_node(self, node: DocumentNode) -> DocumentNode:
        self._session.add(
            DocumentNodeRow(
                id=node.id,
                version_id=node.version_id,
                node_type=_as_str(node.node_type),
                title=node.title,
                heading_path=list(node.heading_path),
                content=node.content,
                parent_id=node.parent_id,
                child_ids=dump_uuids(node.child_ids),
                code_refs=list(node.code_refs),
                requirement_refs=dump_uuids(node.requirement_refs),
                work_item_refs=dump_uuids(node.work_item_refs),
                links=list(node.links),
                unresolved_refs=list(node.unresolved_refs),
            )
        )
        await self._session.flush()
        return node

    async def list_nodes(self, version_id: DocumentVersionId) -> list[DocumentNode]:
        result = await self._session.execute(
            select(DocumentNodeRow).where(DocumentNodeRow.version_id == version_id)
        )
        return [_document_node_from_row(row) for row in result.scalars().all()]


class PostgresExecutionRepository(_PostgresRepository):
    async def create(self, execution: Execution) -> Execution:
        self._session.add(_execution_row(execution))
        await self._session.flush()
        return execution

    async def get(self, execution_id: ExecutionId) -> Execution | None:
        row = await self._session.get(ExecutionRow, execution_id)
        return _execution_from_row(row) if row is not None else None

    async def list_by_work_item(self, work_item_id: WorkItemId) -> list[Execution]:
        result = await self._session.execute(
            select(ExecutionRow)
            .where(ExecutionRow.work_item_id == work_item_id)
            .order_by(ExecutionRow.started_at)
        )
        return [_execution_from_row(row) for row in result.scalars().all()]

    async def update(self, execution: Execution) -> Execution:
        row = await self._session.get(ExecutionRow, execution.id)
        if row is None:
            return await self.create(execution)
        _apply_execution(row, execution)
        await self._session.flush()
        return execution


class PostgresDecisionRepository(_PostgresRepository):
    async def create(self, decision: Decision) -> Decision:
        self._session.add(_decision_row(decision))
        await self._replace_external_refs("decision", decision.id, decision.external_refs)
        await self._session.flush()
        return decision

    async def get(self, decision_id: DecisionId) -> Decision | None:
        row = await self._session.get(DecisionRow, decision_id)
        return _decision_from_row(row) if row is not None else None

    async def list_by_project(self, project_id: ProjectId) -> list[Decision]:
        result = await self._session.execute(
            select(DecisionRow)
            .where(DecisionRow.project_id == project_id)
            .order_by(DecisionRow.title)
        )
        return [_decision_from_row(row) for row in result.scalars().all()]

    async def update(self, decision: Decision) -> Decision:
        row = await self._session.get(DecisionRow, decision.id)
        if row is None:
            return await self.create(decision)
        _apply_decision(row, decision)
        await self._replace_external_refs("decision", decision.id, decision.external_refs)
        await self._session.flush()
        return decision

    async def delete(self, decision_id: DecisionId) -> None:
        row = await self._session.get(DecisionRow, decision_id)
        if row is not None:
            await self._session.delete(row)
            await self._delete_external_refs("decision", decision_id)
            await self._session.flush()


class PostgresEvidenceRepository(_PostgresRepository):
    async def create(self, evidence: Evidence) -> Evidence:
        self._session.add(
            EvidenceRow(
                id=evidence.id,
                execution_id=evidence.execution_id,
                evidence_type=_as_str(evidence.evidence_type),
                source=evidence.source,
                artifact_id=evidence.artifact_id,
                payload=evidence.payload,
            )
        )
        await self._session.flush()
        return evidence

    async def get(self, evidence_id: EvidenceId) -> Evidence | None:
        row = await self._session.get(EvidenceRow, evidence_id)
        return _evidence_from_row(row) if row is not None else None

    async def list_by_execution(self, execution_id: ExecutionId) -> list[Evidence]:
        result = await self._session.execute(
            select(EvidenceRow).where(EvidenceRow.execution_id == execution_id)
        )
        return [_evidence_from_row(row) for row in result.scalars().all()]


class PostgresArtifactRepository(_PostgresRepository):
    async def create(self, artifact: Artifact) -> Artifact:
        self._session.add(
            ArtifactRow(
                id=artifact.id,
                project_id=artifact.project_id,
                artifact_type=_as_str(artifact.artifact_type),
                uri=artifact.uri,
                checksum=artifact.checksum,
                repository_id=artifact.repository_id,
                commit_sha=artifact.commit_sha,
                execution_id=artifact.execution_id,
            )
        )
        await self._session.flush()
        return artifact

    async def get(self, artifact_id: ArtifactId) -> Artifact | None:
        row = await self._session.get(ArtifactRow, artifact_id)
        return _artifact_from_row(row) if row is not None else None

    async def list_by_project(self, project_id: ProjectId) -> list[Artifact]:
        result = await self._session.execute(
            select(ArtifactRow).where(ArtifactRow.project_id == project_id)
        )
        return [_artifact_from_row(row) for row in result.scalars().all()]


class PostgresVerificationResultRepository(_PostgresRepository):
    async def create(self, result: VerificationResult) -> VerificationResult:
        self._session.add(
            VerificationResultRow(
                id=result.id,
                execution_id=result.execution_id,
                verdict=_as_str(result.verdict),
                requirement_results=result.requirement_results,
                test_results=result.test_results,
                architecture_results=result.architecture_results,
                static_analysis_results=result.static_analysis_results,
                issues=list(result.issues),
                evidence_refs=dump_uuids(result.evidence_refs),
            )
        )
        await self._session.flush()
        return result

    async def get(self, verification_id: VerificationId) -> VerificationResult | None:
        row = await self._session.get(VerificationResultRow, verification_id)
        return _verification_result_from_row(row) if row is not None else None

    async def list_by_execution(self, execution_id: ExecutionId) -> list[VerificationResult]:
        result = await self._session.execute(
            select(VerificationResultRow).where(VerificationResultRow.execution_id == execution_id)
        )
        return [_verification_result_from_row(row) for row in result.scalars().all()]


def _work_item_row(work_item: WorkItem) -> WorkItemRow:
    return WorkItemRow(
        id=work_item.id,
        project_id=work_item.project_id,
        type=_as_str(work_item.type),
        title=work_item.title,
        description=work_item.description,
        priority=work_item.priority.value if work_item.priority is not None else None,
        parent_id=work_item.parent_id,
        assignee=work_item.assignee,
        assignment=work_item.assignment.model_dump(mode="json") if work_item.assignment else None,
        acceptance_criteria=dump_models(work_item.acceptance_criteria),
        requirement_refs=dump_uuids(work_item.requirement_refs),
        external_refs=dump_models(work_item.external_refs),
        human_work_status=_as_str(work_item.human_work_status),
        implementation_status=_as_str(work_item.implementation_status),
        verification_status=_as_str(work_item.verification_status),
        pull_request_status=_as_str(work_item.pull_request_status),
    )


def _apply_work_item(row: WorkItemRow, work_item: WorkItem) -> None:
    row.project_id = work_item.project_id
    row.type = work_item.type.value
    row.title = work_item.title
    row.description = work_item.description
    row.priority = work_item.priority.value if work_item.priority is not None else None
    row.parent_id = work_item.parent_id
    row.assignee = work_item.assignee
    row.assignment = work_item.assignment.model_dump(mode="json") if work_item.assignment else None
    row.acceptance_criteria = dump_models(work_item.acceptance_criteria)
    row.requirement_refs = dump_uuids(work_item.requirement_refs)
    row.external_refs = dump_models(work_item.external_refs)
    row.human_work_status = work_item.human_work_status.value
    row.implementation_status = work_item.implementation_status.value
    row.verification_status = work_item.verification_status.value
    row.pull_request_status = work_item.pull_request_status.value


def _requirement_row(requirement: Requirement) -> RequirementRow:
    return RequirementRow(
        id=requirement.id,
        project_id=requirement.project_id,
        key=requirement.key,
        title=requirement.title,
        description=requirement.description,
        status=_as_str(requirement.status),
        priority=requirement.priority.value if requirement.priority is not None else None,
        parent_id=requirement.parent_id,
        derived_from=dump_uuids(requirement.derived_from),
        acceptance_criteria=dump_models(requirement.acceptance_criteria),
        constraints=dump_models(requirement.constraints),
        source_refs=dump_models(requirement.source_refs),
    )


def _apply_requirement(row: RequirementRow, requirement: Requirement) -> None:
    row.project_id = requirement.project_id
    row.key = requirement.key
    row.title = requirement.title
    row.description = requirement.description
    row.status = requirement.status.value
    row.priority = requirement.priority.value if requirement.priority is not None else None
    row.parent_id = requirement.parent_id
    row.derived_from = dump_uuids(requirement.derived_from)
    row.acceptance_criteria = dump_models(requirement.acceptance_criteria)
    row.constraints = dump_models(requirement.constraints)
    row.source_refs = dump_models(requirement.source_refs)


def _execution_row(execution: Execution) -> ExecutionRow:
    return ExecutionRow(
        id=execution.id,
        workflow_id=execution.workflow_id,
        work_item_id=execution.work_item_id,
        executor_id=execution.executor_id,
        context_capsule_id=execution.context_capsule_id,
        status=_as_str(execution.status),
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        parent_execution_id=execution.parent_execution_id,
        correlation_id=execution.correlation_id,
    )


def _apply_execution(row: ExecutionRow, execution: Execution) -> None:
    row.workflow_id = execution.workflow_id
    row.work_item_id = execution.work_item_id
    row.executor_id = execution.executor_id
    row.context_capsule_id = execution.context_capsule_id
    row.status = execution.status.value
    row.started_at = execution.started_at
    row.completed_at = execution.completed_at
    row.parent_execution_id = execution.parent_execution_id
    row.correlation_id = execution.correlation_id


def _decision_row(decision: Decision) -> DecisionRow:
    return DecisionRow(
        id=decision.id,
        project_id=decision.project_id,
        title=decision.title,
        context=decision.context,
        decision=decision.decision,
        alternatives=list(decision.alternatives),
        consequences=list(decision.consequences),
        status=_as_str(decision.status),
        source_refs=dump_models(decision.source_refs),
        external_refs=dump_models(decision.external_refs),
    )


def _apply_decision(row: DecisionRow, decision: Decision) -> None:
    row.project_id = decision.project_id
    row.title = decision.title
    row.context = decision.context
    row.decision = decision.decision
    row.alternatives = list(decision.alternatives)
    row.consequences = list(decision.consequences)
    row.status = decision.status.value
    row.source_refs = dump_models(decision.source_refs)
    row.external_refs = dump_models(decision.external_refs)


def _project_from_row(row: ProjectRow) -> Project:
    return Project.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "status": row.status,
            "repositories": row.repositories,
            "external_refs": row.external_refs,
        }
    )


def _repository_from_row(row: RepositoryRow) -> Repository:
    return Repository.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "name": row.name,
            "clone_url": row.clone_url,
            "default_branch": row.default_branch,
            "current_revision": row.current_revision,
            "external_refs": row.external_refs,
        }
    )


def _actor_from_row(row: ActorRow) -> Actor:
    return Actor.model_validate(
        {
            "id": row.id,
            "actor_type": row.actor_type,
            "display_name": row.display_name,
            "capabilities": row.capabilities,
        }
    )


def _work_item_from_row(row: WorkItemRow) -> WorkItem:
    return WorkItem.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "type": row.type,
            "title": row.title,
            "description": row.description,
            "priority": row.priority,
            "parent_id": row.parent_id,
            "assignee": row.assignee,
            "assignment": row.assignment,
            "acceptance_criteria": row.acceptance_criteria,
            "requirement_refs": row.requirement_refs,
            "external_refs": row.external_refs,
            "human_work_status": row.human_work_status,
            "implementation_status": row.implementation_status,
            "verification_status": row.verification_status,
            "pull_request_status": row.pull_request_status,
        }
    )


def _requirement_from_row(row: RequirementRow) -> Requirement:
    return Requirement.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "key": row.key,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "priority": row.priority,
            "parent_id": row.parent_id,
            "derived_from": row.derived_from,
            "acceptance_criteria": row.acceptance_criteria,
            "constraints": row.constraints,
            "source_refs": row.source_refs,
        }
    )


def _document_from_row(row: DocumentRow) -> Document:
    return Document.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "type": row.type,
            "title": row.title,
            "source": row.source,
            "current_version_id": row.current_version_id,
            "external_refs": row.external_refs,
        }
    )


def _document_version_from_row(row: DocumentVersionRow) -> DocumentVersion:
    return DocumentVersion.model_validate(
        {
            "id": row.id,
            "document_id": row.document_id,
            "source_version": row.source_version,
            "repository_id": row.repository_id,
            "commit_sha": row.commit_sha,
            "checksum": row.checksum,
            "ingested_at": row.ingested_at,
            "content_uri": row.content_uri,
        }
    )


def _document_node_from_row(row: DocumentNodeRow) -> DocumentNode:
    return DocumentNode.model_validate(
        {
            "id": row.id,
            "version_id": row.version_id,
            "node_type": row.node_type,
            "title": row.title,
            "heading_path": row.heading_path,
            "content": row.content,
            "parent_id": row.parent_id,
            "child_ids": row.child_ids,
            "code_refs": row.code_refs,
            "requirement_refs": row.requirement_refs,
            "work_item_refs": row.work_item_refs,
            "links": row.links,
            "unresolved_refs": row.unresolved_refs,
        }
    )


def _execution_from_row(row: ExecutionRow) -> Execution:
    return Execution.model_validate(
        {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "work_item_id": row.work_item_id,
            "executor_id": row.executor_id,
            "context_capsule_id": row.context_capsule_id,
            "status": row.status,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "parent_execution_id": row.parent_execution_id,
            "correlation_id": row.correlation_id,
        }
    )


def _decision_from_row(row: DecisionRow) -> Decision:
    return Decision.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "title": row.title,
            "context": row.context,
            "decision": row.decision,
            "alternatives": row.alternatives,
            "consequences": row.consequences,
            "status": row.status,
            "source_refs": row.source_refs,
            "external_refs": row.external_refs,
        }
    )


def _evidence_from_row(row: EvidenceRow) -> Evidence:
    return Evidence.model_validate(
        {
            "id": row.id,
            "execution_id": row.execution_id,
            "evidence_type": row.evidence_type,
            "source": row.source,
            "artifact_id": row.artifact_id,
            "payload": row.payload,
        }
    )


def _artifact_from_row(row: ArtifactRow) -> Artifact:
    return Artifact.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "artifact_type": row.artifact_type,
            "uri": row.uri,
            "checksum": row.checksum,
            "repository_id": row.repository_id,
            "commit_sha": row.commit_sha,
            "execution_id": row.execution_id,
        }
    )


def _verification_result_from_row(row: VerificationResultRow) -> VerificationResult:
    return VerificationResult.model_validate(
        {
            "id": row.id,
            "execution_id": row.execution_id,
            "verdict": row.verdict,
            "requirement_results": row.requirement_results,
            "test_results": row.test_results,
            "architecture_results": row.architecture_results,
            "static_analysis_results": row.static_analysis_results,
            "issues": row.issues,
            "evidence_refs": row.evidence_refs,
        }
    )


class PostgresIdempotencyStore:
    """Durable deduplication of external events (see IdempotencyStore port)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_processed(self, key: str) -> bool:
        result = await self._session.execute(
            select(IdempotencyKeyRow.idempotency_key).where(
                IdempotencyKeyRow.idempotency_key == key
            )
        )
        return result.first() is not None

    async def mark_processed(self, key: str, event_id: uuid.UUID | None = None) -> None:
        await self._session.execute(
            pg_insert(IdempotencyKeyRow)
            .values(idempotency_key=key, event_id=event_id)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.flush()


def _envelope_from_row(row: EventLogRow) -> EventEnvelope:
    return EventEnvelope.model_validate(
        {
            "event_id": row.event_id,
            "event_type": row.event_type,
            "occurred_at": row.occurred_at,
            "project_id": row.project_id,
            "correlation_id": row.correlation_id,
            "causation_id": row.causation_id,
            "source": row.source,
            "idempotency_key": row.idempotency_key,
            "payload": row.payload,
        }
    )


class PostgresEventLogRepository:
    """Append-only log of processed canonical events (see EventLogRepository port)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: EventEnvelope) -> None:
        self._session.add(
            EventLogRow(
                event_id=event.event_id,
                event_type=event.event_type.value,
                project_id=event.project_id,
                occurred_at=event.occurred_at,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                source=event.source,
                idempotency_key=event.idempotency_key,
                payload=event.payload,
            )
        )
        await self._session.flush()

    async def list_by_correlation(self, correlation_id: uuid.UUID) -> list[EventEnvelope]:
        result = await self._session.execute(
            select(EventLogRow)
            .where(EventLogRow.correlation_id == correlation_id)
            .order_by(EventLogRow.id)
        )
        return [_envelope_from_row(row) for row in result.scalars().all()]

    async def list_recent(self, limit: int = 100) -> list[EventEnvelope]:
        result = await self._session.execute(
            select(EventLogRow).order_by(EventLogRow.id.desc()).limit(limit)
        )
        return [_envelope_from_row(row) for row in reversed(result.scalars().all())]


class PostgresRepositorySnapshotRepository(_PostgresRepository):
    """Durable repository snapshots (see RepositorySnapshotRepository port)."""

    async def save_snapshot(self, snapshot: RepositorySnapshot) -> RepositorySnapshot:
        stmt = pg_insert(RepositorySnapshotRow).values(
            id=snapshot.id,
            repository_id=snapshot.repository_id,
            revision=snapshot.revision,
            captured_at=snapshot.captured_at,
            tree=list(snapshot.tree),
            languages=list(snapshot.languages),
            manifest_files=list(snapshot.manifest_files),
            dockerfiles=list(snapshot.dockerfiles),
            compose_files=list(snapshot.compose_files),
            ci_configuration=list(snapshot.ci_configuration),
            documentation_roots=list(snapshot.documentation_roots),
            test_roots=list(snapshot.test_roots),
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["repository_id", "revision"],
                set_={
                    "id": snapshot.id,
                    "captured_at": snapshot.captured_at,
                    "tree": list(snapshot.tree),
                    "languages": list(snapshot.languages),
                    "manifest_files": list(snapshot.manifest_files),
                    "dockerfiles": list(snapshot.dockerfiles),
                    "compose_files": list(snapshot.compose_files),
                    "ci_configuration": list(snapshot.ci_configuration),
                    "documentation_roots": list(snapshot.documentation_roots),
                    "test_roots": list(snapshot.test_roots),
                },
            )
        )
        await self._session.flush()
        return snapshot

    async def get_snapshot(
        self, repository_id: RepositoryId, revision: str
    ) -> RepositorySnapshot | None:
        result = await self._session.execute(
            select(RepositorySnapshotRow).where(
                RepositorySnapshotRow.repository_id == repository_id,
                RepositorySnapshotRow.revision == revision,
            )
        )
        row = result.scalar_one_or_none()
        return _snapshot_from_row(row) if row is not None else None

    async def list_snapshots(self, repository_id: RepositoryId) -> list[RepositorySnapshot]:
        result = await self._session.execute(
            select(RepositorySnapshotRow)
            .where(RepositorySnapshotRow.repository_id == repository_id)
            .order_by(RepositorySnapshotRow.captured_at)
        )
        return [_snapshot_from_row(row) for row in result.scalars().all()]


class PostgresRepositoryChangeSetRepository(_PostgresRepository):
    """Durable classified change sets (see RepositoryChangeSetRepository port)."""

    async def save_change_set(self, change_set: RepositoryChangeSet) -> RepositoryChangeSet:
        self._session.add(
            RepositoryChangeSetRow(
                id=change_set.id,
                repository_id=change_set.repository_id,
                old_revision=change_set.old_revision,
                new_revision=change_set.new_revision,
                detected_at=change_set.detected_at,
                files=dump_models(change_set.files),
            )
        )
        await self._session.flush()
        return change_set

    async def list_change_sets(self, repository_id: RepositoryId) -> list[RepositoryChangeSet]:
        result = await self._session.execute(
            select(RepositoryChangeSetRow)
            .where(RepositoryChangeSetRow.repository_id == repository_id)
            .order_by(RepositoryChangeSetRow.detected_at)
        )
        return [_change_set_from_row(row) for row in result.scalars().all()]


def _snapshot_from_row(row: RepositorySnapshotRow) -> RepositorySnapshot:
    return RepositorySnapshot.model_validate(
        {
            "id": row.id,
            "repository_id": row.repository_id,
            "revision": row.revision,
            "captured_at": row.captured_at,
            "tree": row.tree,
            "languages": row.languages,
            "manifest_files": row.manifest_files,
            "dockerfiles": row.dockerfiles,
            "compose_files": row.compose_files,
            "ci_configuration": row.ci_configuration,
            "documentation_roots": row.documentation_roots,
            "test_roots": row.test_roots,
        }
    )


def _change_set_from_row(row: RepositoryChangeSetRow) -> RepositoryChangeSet:
    return RepositoryChangeSet.model_validate(
        {
            "id": row.id,
            "repository_id": row.repository_id,
            "old_revision": row.old_revision,
            "new_revision": row.new_revision,
            "detected_at": row.detected_at,
            "files": [_changed_file_from_dict(f) for f in row.files],
        }
    )


def _changed_file_from_dict(data: dict[str, object]) -> ChangedFile:
    return ChangedFile(
        path=str(data["path"]),
        category=FileCategory(str(data["category"])),
        change_type=str(data.get("change_type", "modified")),
    )
