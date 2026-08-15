"""In-memory reference implementations of the state repository ports.

These exist so application services can be tested without PostgreSQL and so
the contract tests have a reference behavior to compare future adapters
against.  They are intentionally simple (full scans for filters).
"""

from __future__ import annotations

from brain.adapters.in_memory.base import InMemoryCollection
from brain.domain.actors import Actor
from brain.domain.artifacts import Artifact
from brain.domain.decisions import Decision
from brain.domain.documents import Document, DocumentNode, DocumentVersion
from brain.domain.evidence import Evidence
from brain.domain.executions import Execution
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
from brain.domain.requirements import Requirement
from brain.domain.verification import VerificationResult
from brain.domain.work_items import WorkItem


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects = InMemoryCollection[Project]()

    async def create(self, project: Project) -> Project:
        return await self._projects.upsert(project, project.id)

    async def get(self, project_id: ProjectId) -> Project | None:
        return await self._projects.get(project_id)

    async def list(self) -> list[Project]:
        return await self._projects.list_all()

    async def update(self, project: Project) -> Project:
        return await self._projects.upsert(project, project.id)

    async def delete(self, project_id: ProjectId) -> None:
        await self._projects.delete(project_id)


class InMemoryRepositoryRepository:
    def __init__(self) -> None:
        self._repositories = InMemoryCollection[Repository]()

    async def create(self, repository: Repository) -> Repository:
        return await self._repositories.upsert(repository, repository.id)

    async def get(self, repository_id: RepositoryId) -> Repository | None:
        return await self._repositories.get(repository_id)

    async def list_by_project(self, project_id: ProjectId) -> list[Repository]:
        return [r for r in await self._repositories.list_all() if r.project_id == project_id]

    async def update(self, repository: Repository) -> Repository:
        return await self._repositories.upsert(repository, repository.id)

    async def delete(self, repository_id: RepositoryId) -> None:
        await self._repositories.delete(repository_id)


class InMemoryActorRepository:
    def __init__(self) -> None:
        self._actors = InMemoryCollection[Actor]()

    async def create(self, actor: Actor) -> Actor:
        return await self._actors.upsert(actor, actor.id)

    async def get(self, actor_id: ActorId) -> Actor | None:
        return await self._actors.get(actor_id)

    async def list(self) -> list[Actor]:
        return await self._actors.list_all()

    async def update(self, actor: Actor) -> Actor:
        return await self._actors.upsert(actor, actor.id)

    async def delete(self, actor_id: ActorId) -> None:
        await self._actors.delete(actor_id)


class InMemoryWorkItemRepository:
    def __init__(self) -> None:
        self._work_items = InMemoryCollection[WorkItem]()

    async def create(self, work_item: WorkItem) -> WorkItem:
        return await self._work_items.upsert(work_item, work_item.id)

    async def get(self, work_item_id: WorkItemId) -> WorkItem | None:
        return await self._work_items.get(work_item_id)

    async def list_by_project(self, project_id: ProjectId) -> list[WorkItem]:
        return [w for w in await self._work_items.list_all() if w.project_id == project_id]

    async def list_by_work_item(self, parent_id: WorkItemId) -> list[WorkItem]:
        return [w for w in await self._work_items.list_all() if w.parent_id == parent_id]

    async def update(self, work_item: WorkItem) -> WorkItem:
        return await self._work_items.upsert(work_item, work_item.id)

    async def delete(self, work_item_id: WorkItemId) -> None:
        await self._work_items.delete(work_item_id)


class InMemoryRequirementRepository:
    def __init__(self) -> None:
        self._requirements = InMemoryCollection[Requirement]()

    async def create(self, requirement: Requirement) -> Requirement:
        return await self._requirements.upsert(requirement, requirement.id)

    async def get(self, requirement_id: RequirementId) -> Requirement | None:
        return await self._requirements.get(requirement_id)

    async def list_by_project(self, project_id: ProjectId) -> list[Requirement]:
        return [r for r in await self._requirements.list_all() if r.project_id == project_id]

    async def list_by_parent(self, parent_id: RequirementId) -> list[Requirement]:
        return [r for r in await self._requirements.list_all() if r.parent_id == parent_id]

    async def update(self, requirement: Requirement) -> Requirement:
        return await self._requirements.upsert(requirement, requirement.id)

    async def delete(self, requirement_id: RequirementId) -> None:
        await self._requirements.delete(requirement_id)


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._documents = InMemoryCollection[Document]()
        self._versions = InMemoryCollection[DocumentVersion]()
        self._nodes = InMemoryCollection[DocumentNode]()

    async def create(self, document: Document) -> Document:
        return await self._documents.upsert(document, document.id)

    async def get(self, document_id: DocumentId) -> Document | None:
        return await self._documents.get(document_id)

    async def list_by_project(self, project_id: ProjectId) -> list[Document]:
        return [d for d in await self._documents.list_all() if d.project_id == project_id]

    async def update(self, document: Document) -> Document:
        return await self._documents.upsert(document, document.id)

    async def delete(self, document_id: DocumentId) -> None:
        await self._documents.delete(document_id)

    async def add_version(self, version: DocumentVersion) -> DocumentVersion:
        return await self._versions.upsert(version, version.id)

    async def get_version(self, version_id: DocumentVersionId) -> DocumentVersion | None:
        return await self._versions.get(version_id)

    async def list_versions(self, document_id: DocumentId) -> list[DocumentVersion]:
        return [v for v in await self._versions.list_all() if v.document_id == document_id]

    async def add_node(self, node: DocumentNode) -> DocumentNode:
        return await self._nodes.upsert(node, node.id)

    async def list_nodes(self, version_id: DocumentVersionId) -> list[DocumentNode]:
        return [n for n in await self._nodes.list_all() if n.version_id == version_id]


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self._executions = InMemoryCollection[Execution]()

    async def create(self, execution: Execution) -> Execution:
        return await self._executions.upsert(execution, execution.id)

    async def get(self, execution_id: ExecutionId) -> Execution | None:
        return await self._executions.get(execution_id)

    async def list_by_work_item(self, work_item_id: WorkItemId) -> list[Execution]:
        return [e for e in await self._executions.list_all() if e.work_item_id == work_item_id]

    async def update(self, execution: Execution) -> Execution:
        return await self._executions.upsert(execution, execution.id)


class InMemoryDecisionRepository:
    def __init__(self) -> None:
        self._decisions = InMemoryCollection[Decision]()

    async def create(self, decision: Decision) -> Decision:
        return await self._decisions.upsert(decision, decision.id)

    async def get(self, decision_id: DecisionId) -> Decision | None:
        return await self._decisions.get(decision_id)

    async def list_by_project(self, project_id: ProjectId) -> list[Decision]:
        return [d for d in await self._decisions.list_all() if d.project_id == project_id]

    async def update(self, decision: Decision) -> Decision:
        return await self._decisions.upsert(decision, decision.id)

    async def delete(self, decision_id: DecisionId) -> None:
        await self._decisions.delete(decision_id)


class InMemoryEvidenceRepository:
    def __init__(self) -> None:
        self._evidence = InMemoryCollection[Evidence]()

    async def create(self, evidence: Evidence) -> Evidence:
        return await self._evidence.upsert(evidence, evidence.id)

    async def get(self, evidence_id: EvidenceId) -> Evidence | None:
        return await self._evidence.get(evidence_id)

    async def list_by_execution(self, execution_id: ExecutionId) -> list[Evidence]:
        return [e for e in await self._evidence.list_all() if e.execution_id == execution_id]


class InMemoryArtifactRepository:
    def __init__(self) -> None:
        self._artifacts = InMemoryCollection[Artifact]()

    async def create(self, artifact: Artifact) -> Artifact:
        return await self._artifacts.upsert(artifact, artifact.id)

    async def get(self, artifact_id: ArtifactId) -> Artifact | None:
        return await self._artifacts.get(artifact_id)

    async def list_by_project(self, project_id: ProjectId) -> list[Artifact]:
        return [a for a in await self._artifacts.list_all() if a.project_id == project_id]


class InMemoryVerificationResultRepository:
    def __init__(self) -> None:
        self._results = InMemoryCollection[VerificationResult]()

    async def create(self, result: VerificationResult) -> VerificationResult:
        return await self._results.upsert(result, result.id)

    async def get(self, verification_id: VerificationId) -> VerificationResult | None:
        return await self._results.get(verification_id)

    async def list_by_execution(self, execution_id: ExecutionId) -> list[VerificationResult]:
        return [v for v in await self._results.list_all() if v.execution_id == execution_id]
