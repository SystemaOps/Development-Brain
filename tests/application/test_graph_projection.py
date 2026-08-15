"""Unit tests for the Phase 8 graph projection, reconciliation, and integrity."""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryRepositoryRepository,
    InMemoryRequirementRepository,
    InMemorySoftwareCatalogRepository,
    InMemoryWorkItemRepository,
)
from brain.application.graph_integrity import GraphIntegrityChecker
from brain.application.graph_projection import GraphProjectionService
from brain.domain.decisions import Decision
from brain.domain.graph_reconciliation import GraphReconciler, RelationClaim
from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.knowledge import (
    DiscoveryMethod,
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeOrigin,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.requirements import Requirement
from brain.domain.software_model import (
    ComponentType,
    SoftwareComponent,
)
from brain.domain.work_items import WorkItem
from brain.ports.knowledge_graph import GraphEntity, GraphRelation


def _evidence(
    origin: KnowledgeOrigin = KnowledgeOrigin.DISCOVERED,
    confidence: KnowledgeConfidence = KnowledgeConfidence.HIGH,
) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_type="test",
        discovery_method=DiscoveryMethod.MANIFEST_ANALYSIS,
        origin=origin,
        confidence=confidence,
    )


@pytest.fixture
def graph() -> InMemoryKnowledgeGraph:
    return InMemoryKnowledgeGraph()


def _projection_service(graph: InMemoryKnowledgeGraph) -> GraphProjectionService:
    return GraphProjectionService(
        graph=graph,
        projects=object(),
        requirements=InMemoryRequirementRepository(),
        work_items=InMemoryWorkItemRepository(),
        repositories=InMemoryRepositoryRepository(),
        catalog=InMemorySoftwareCatalogRepository(),
        decisions=InMemoryDecisionRepository(),
        code_graph=InMemoryCodeGraphRepository(),
    )


async def test_projection_projects_canonical_entities(graph: InMemoryKnowledgeGraph) -> None:
    project = Project(name="auth")
    repositories = InMemoryRepositoryRepository()
    requirements = InMemoryRequirementRepository()
    work_items = InMemoryWorkItemRepository()
    catalog = InMemorySoftwareCatalogRepository()
    decisions = InMemoryDecisionRepository()
    code_graph = InMemoryCodeGraphRepository()

    repository = Repository(
        project_id=project.id, name="auth-service", clone_url="git@example:auth.git"
    )
    await repositories.create(repository)
    requirement = Requirement(project_id=project.id, title="Login required", key="REQ-1")
    await requirements.create(requirement)
    work_item = WorkItem(
        project_id=project.id, title="Implement login", requirement_refs=[requirement.id]
    )
    await work_items.create(work_item)
    component = SoftwareComponent(
        project_id=project.id,
        name="auth",
        component_type=ComponentType.BACKEND_SERVICE,
        repository_ids=[repository.id],
    )
    await catalog.upsert_component(component)
    decision = Decision(project_id=project.id, title="Auth component decision")
    await decisions.create(decision)

    service = GraphProjectionService(
        graph=graph,
        projects=object(),
        requirements=requirements,
        work_items=work_items,
        repositories=repositories,
        catalog=catalog,
        decisions=decisions,
        code_graph=code_graph,
    )
    result = await service.project(project)

    labels = {e.label for e in result.entities}
    assert GraphLabel.PROJECT in labels
    assert GraphLabel.REPOSITORY in labels
    assert GraphLabel.REQUIREMENT in labels
    assert GraphLabel.WORK_ITEM in labels
    assert GraphLabel.COMPONENT in labels
    assert GraphLabel.DECISION in labels

    types = {r.relation_type for r in result.relations}
    assert RelationType.PART_OF in types
    assert RelationType.IMPLEMENTS in types  # work item -> requirement
    assert RelationType.DEPENDS_ON in types  # component -> repository


async def test_projection_links_component_to_repository(graph: InMemoryKnowledgeGraph) -> None:
    project = Project(name="auth")
    repositories = InMemoryRepositoryRepository()
    repository = Repository(
        project_id=project.id, name="auth-service", clone_url="git@example:auth.git"
    )
    await repositories.create(repository)
    catalog = InMemorySoftwareCatalogRepository()
    await catalog.upsert_component(
        SoftwareComponent(
            project_id=project.id,
            name="auth",
            component_type=ComponentType.BACKEND_SERVICE,
            repository_ids=[repository.id],
        )
    )
    service = GraphProjectionService(
        graph=graph,
        projects=object(),
        requirements=InMemoryRequirementRepository(),
        work_items=InMemoryWorkItemRepository(),
        repositories=repositories,
        catalog=catalog,
        decisions=InMemoryDecisionRepository(),
        code_graph=InMemoryCodeGraphRepository(),
    )
    result = await service.project(project)
    assert any(
        r.relation_type == RelationType.DEPENDS_ON
        and r.subject_id != repository.id
        and r.object_id == repository.id
        for r in result.relations
    )


async def test_traverse_from_work_item_to_component(graph: InMemoryKnowledgeGraph) -> None:
    """Task 8.5 projection: work item -> requirement -> component reachable."""
    project = Project(name="auth")
    repositories = InMemoryRepositoryRepository()
    repository = Repository(
        project_id=project.id, name="auth-service", clone_url="git@example:auth.git"
    )
    await repositories.create(repository)
    requirements = InMemoryRequirementRepository()
    requirement = Requirement(project_id=project.id, title="Auth service login", key="REQ-1")
    await requirements.create(requirement)
    work_items = InMemoryWorkItemRepository()
    work_item = WorkItem(
        project_id=project.id, title="Implement login", requirement_refs=[requirement.id]
    )
    await work_items.create(work_item)
    catalog = InMemorySoftwareCatalogRepository()
    component = SoftwareComponent(
        project_id=project.id,
        name="auth",
        component_type=ComponentType.BACKEND_SERVICE,
        repository_ids=[repository.id],
    )
    await catalog.upsert_component(component)

    service = GraphProjectionService(
        graph=graph,
        projects=object(),
        requirements=requirements,
        work_items=work_items,
        repositories=repositories,
        catalog=catalog,
        decisions=InMemoryDecisionRepository(),
        code_graph=InMemoryCodeGraphRepository(),
    )
    await service.project(project)

    reached = await graph.traverse(
        [work_item.id],
        [RelationType.IMPLEMENTS, RelationType.REFERENCES],
        depth=3,
    )
    labels = {e.label for e in reached}
    assert GraphLabel.REQUIREMENT in labels
    assert GraphLabel.COMPONENT in labels


async def test_reconciler_declared_beats_discovered() -> None:
    claims = [
        RelationClaim(
            relation_type=RelationType.DEPENDS_ON,
            subject_key="payment-service",
            object_key="redis",
            evidence=[_evidence(KnowledgeOrigin.DISCOVERED, KnowledgeConfidence.HIGH)],
        ),
        RelationClaim(
            relation_type=RelationType.DEPENDS_ON,
            subject_key="payment-service",
            object_key="redis",
            evidence=[_evidence(KnowledgeOrigin.DECLARED, KnowledgeConfidence.MEDIUM)],
        ),
    ]
    reconciled = GraphReconciler().reconcile(claims)
    assert len(reconciled) == 1
    assert reconciled[0].origin == "declared"
    assert len(reconciled[0].claims) == 2  # disagreement preserved


async def test_reconciler_keeps_distinct_relations_separate() -> None:
    claims = [
        RelationClaim(
            relation_type=RelationType.DEPENDS_ON,
            subject_key="a",
            object_key="b",
            evidence=[_evidence()],
        ),
        RelationClaim(
            relation_type=RelationType.CALLS,
            subject_key="x",
            object_key="y",
            evidence=[_evidence()],
        ),
    ]
    reconciled = GraphReconciler().reconcile(claims)
    assert len(reconciled) == 2


async def test_integrity_check_clean_graph(graph: InMemoryKnowledgeGraph) -> None:
    project = Project(name="auth")
    a = GraphEntity(
        id=uuid.uuid4(), label=GraphLabel.COMPONENT, project_id=project.id, properties={"name": "a"}
    )
    b = GraphEntity(
        id=uuid.uuid4(), label=GraphLabel.COMPONENT, project_id=project.id, properties={"name": "b"}
    )
    await graph.upsert_entities([a, b])
    await graph.upsert_relations(
        [GraphRelation(subject_id=a.id, relation_type=RelationType.DEPENDS_ON, object_id=b.id)]
    )
    report = await GraphIntegrityChecker(graph=graph).check(project.id)
    assert report.ok, report.issues


async def test_integrity_check_detects_duplicate_nodes() -> None:
    project = Project(name="auth")
    a = GraphEntity(
        id=uuid.uuid4(),
        label=GraphLabel.COMPONENT,
        project_id=project.id,
        properties={"name": "dup"},
    )
    b = GraphEntity(
        id=uuid.uuid4(),
        label=GraphLabel.COMPONENT,
        project_id=project.id,
        properties={"name": "dup"},
    )
    graph = InMemoryKnowledgeGraph()
    await graph.upsert_entities([a, b])
    report = await GraphIntegrityChecker(graph=graph).check(project.id)
    categories = {issue.category for issue in report.issues}
    assert "duplicate_node" in categories


async def test_integrity_check_detects_orphans() -> None:
    graph = InMemoryKnowledgeGraph()
    start = uuid.uuid4()
    await graph.upsert_relations(
        [GraphRelation(subject_id=start, relation_type=RelationType.CALLS, object_id=uuid.uuid4())]
    )
    report = await GraphIntegrityChecker(graph=graph).check()
    categories = {issue.category for issue in report.issues}
    assert "orphan_subject" in categories
    assert "orphan_object" in categories
