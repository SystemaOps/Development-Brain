"""Phase 8 golden tests and completion gate.

Given a project with a requirement, a work item implementing it, a component
backing a repository with code (files -> symbols -> tests) parsed at one
revision, the projected knowledge graph answers the gate: a task can be
traversed to requirement -> component -> repository -> files -> symbols ->
tests, and the graph passes integrity checks.
"""

from __future__ import annotations

import pytest

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryRepositoryRepository,
    InMemoryRequirementRepository,
    InMemorySoftwareCatalogRepository,
    InMemoryWorkItemRepository,
)
from brain.application.code_intelligence import CodeIntelligenceService
from brain.application.graph_integrity import GraphIntegrityChecker
from brain.application.graph_projection import GraphProjectionService
from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.requirements import Requirement
from brain.domain.software_model import ComponentType, SoftwareComponent
from brain.domain.work_items import WorkItem

REVISION = "abc123"

REPOSITORY_FILES: dict[str, str] = {
    "app/__init__.py": "",
    "app/models.py": """
class User:
    def __init__(self, uid: str) -> None:
        self.uid = uid
""",
    "app/repository.py": """
from .models import User

class UserRepository:
    def get(self, uid: str) -> User:
        return User(uid=uid)
""",
    "app/service.py": """
from .models import User
from .repository import UserRepository

class AuthService:
    def __init__(self) -> None:
        self.repo = UserRepository()

    def login(self, uid: str) -> User:
        return self.repo.get(uid)
""",
    "tests/test_auth.py": """
from app.service import AuthService

def test_login_returns_user() -> None:
    assert AuthService().login("u1").uid == "u1"
""",
}


@pytest.fixture
def graph() -> InMemoryKnowledgeGraph:
    return InMemoryKnowledgeGraph()


async def _seed_and_project(graph: InMemoryKnowledgeGraph) -> dict[str, object]:
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
        project_id=project.id,
        title="Implement auth login",
        requirement_refs=[requirement.id],
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

    code_graph = InMemoryCodeGraphRepository()
    code_service = CodeIntelligenceService(parser=PythonAstParser(), repository=code_graph)
    code_result = await code_service.build_revision(repository.id, REVISION, REPOSITORY_FILES)

    service = GraphProjectionService(
        graph=graph,
        projects=object(),
        requirements=requirements,
        work_items=work_items,
        repositories=repositories,
        catalog=catalog,
        decisions=InMemoryDecisionRepository(),
        code_graph=code_graph,
    )
    await service.project(project, revision=REVISION)

    return {
        "project": project,
        "requirement": requirement,
        "work_item": work_item,
        "repository": repository,
        "component": component,
        "code_result": code_result,
    }


async def test_gate_task_traverses_to_requirement_and_component(
    graph: InMemoryKnowledgeGraph,
) -> None:
    seeded = await _seed_and_project(graph)
    work_item = seeded["work_item"]
    assert isinstance(work_item, WorkItem)

    reached = await graph.traverse(
        [work_item.id],
        [RelationType.IMPLEMENTS, RelationType.REFERENCES],
        depth=3,
    )
    labels = {e.label for e in reached}
    assert GraphLabel.REQUIREMENT in labels
    assert GraphLabel.COMPONENT in labels


async def test_gate_component_traverses_to_repository(
    graph: InMemoryKnowledgeGraph,
) -> None:
    seeded = await _seed_and_project(graph)
    component = seeded["component"]
    repository = seeded["repository"]
    assert isinstance(component, SoftwareComponent)
    assert isinstance(repository, Repository)

    reached = await graph.traverse(
        [component.id],
        [RelationType.DEPENDS_ON],
        depth=1,
    )
    ids = {e.id for e in reached}
    assert repository.id in ids


async def test_gate_repository_traverses_to_files_symbols_tests(
    graph: InMemoryKnowledgeGraph,
) -> None:
    seeded = await _seed_and_project(graph)
    repository = seeded["repository"]
    assert isinstance(repository, Repository)

    reached = await graph.traverse_reverse(
        [repository.id],
        [RelationType.PART_OF],
        depth=2,
    )
    labels = {e.label for e in reached}
    assert GraphLabel.FILE in labels
    assert GraphLabel.SYMBOL in labels
    assert GraphLabel.TEST in labels


async def test_gate_symbol_graph_relations_present(
    graph: InMemoryKnowledgeGraph,
) -> None:
    seeded = await _seed_and_project(graph)
    repository = seeded["repository"]
    assert isinstance(repository, Repository)

    relations = await graph.find_relations(revision=REVISION)
    relation_types = {r.relation_type for r in relations}
    assert RelationType.IMPORTS in relation_types
    assert RelationType.CALLS in relation_types
    assert RelationType.TESTS in relation_types


async def test_gate_full_chain_end_to_end(graph: InMemoryKnowledgeGraph) -> None:
    """Traverse from work item all the way to test files."""
    seeded = await _seed_and_project(graph)
    work_item = seeded["work_item"]
    repository = seeded["repository"]
    assert isinstance(work_item, WorkItem)
    assert isinstance(repository, Repository)

    forward = await graph.traverse(
        [work_item.id],
        [RelationType.IMPLEMENTS, RelationType.REFERENCES, RelationType.DEPENDS_ON],
        depth=4,
    )
    forward_labels = {e.label for e in forward}
    assert GraphLabel.REQUIREMENT in forward_labels
    assert GraphLabel.COMPONENT in forward_labels
    assert GraphLabel.REPOSITORY in forward_labels

    # From the repository, traverse outward to files -> symbols -> tests.
    outward = await graph.traverse_reverse(
        [repository.id],
        [RelationType.PART_OF],
        depth=3,
    )
    outward_labels = {e.label for e in outward}
    assert GraphLabel.FILE in outward_labels
    assert GraphLabel.SYMBOL in outward_labels
    assert GraphLabel.TEST in outward_labels


async def test_gate_reverse_traversal_from_symbol_finds_callers(
    graph: InMemoryKnowledgeGraph,
) -> None:
    seeded = await _seed_and_project(graph)
    repository = seeded["repository"]
    assert isinstance(repository, Repository)

    symbols = await graph.find_entities(GraphLabel.SYMBOL, revision=REVISION)
    login = next(
        (
            s
            for s in symbols
            if s.properties.get("qualified_name") == "app.service.AuthService.login"
        ),
        None,
    )
    assert login is not None

    callers = await graph.traverse_reverse(
        [login.id], [RelationType.CALLS], depth=1, revision=REVISION
    )
    caller_names = {
        e.properties.get("qualified_name") for e in callers if e.label == GraphLabel.SYMBOL
    }
    assert "app.router.handle_login" in caller_names or "tests.test_auth" in str(caller_names)


async def test_gate_graph_is_integrity_clean(graph: InMemoryKnowledgeGraph) -> None:
    seeded = await _seed_and_project(graph)
    project = seeded["project"]
    assert isinstance(project, Project)

    report = await GraphIntegrityChecker(graph=graph).check(project.id)
    assert report.ok, report.issues


async def test_gate_neighborhood_from_symbol(graph: InMemoryKnowledgeGraph) -> None:
    seeded = await _seed_and_project(graph)
    repository = seeded["repository"]
    assert isinstance(repository, Repository)

    symbols = await graph.find_entities(GraphLabel.SYMBOL, revision=REVISION)
    login = next(
        (
            s
            for s in symbols
            if s.properties.get("qualified_name") == "app.service.AuthService.login"
        ),
        None,
    )
    assert login is not None
    neighbors = await graph.neighborhood(
        [login.id], [RelationType.CALLS], direction="both", revision=REVISION
    )
    assert any(e.id != login.id for e in neighbors)
