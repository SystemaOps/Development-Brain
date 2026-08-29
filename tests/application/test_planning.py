"""Unit tests for the Phase 11 planning service."""

from __future__ import annotations

import uuid

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.planning import InMemoryPlanRepository
from brain.adapters.in_memory.repositories import (
    InMemoryDocumentRepository,
    InMemoryExecutionRepository,
    InMemoryRequirementRepository,
    InMemoryWorkItemRepository,
)
from brain.application.code_intelligence import CodeIntelligenceService
from brain.application.planning import PlanningService
from brain.domain.documents import (
    Document,
    DocumentNode,
    DocumentNodeType,
    DocumentSource,
    DocumentVersion,
)
from brain.domain.identity import RepositoryId
from brain.domain.planning import (
    ImplementationStatus,
    PlanItemType,
    PlanStatus,
    RequirementClarity,
)
from brain.domain.projects import Project
from brain.domain.requirements import (
    AcceptanceCriterion,
    Constraint,
    Requirement,
)

REVISION = "abc123"


def _planning_service() -> tuple[PlanningService, Project]:
    project = Project(name="auth")
    plans = InMemoryPlanRepository()
    requirements = InMemoryRequirementRepository()
    documents = InMemoryDocumentRepository()
    work_items = InMemoryWorkItemRepository()
    executions = InMemoryExecutionRepository()
    code_graph = InMemoryCodeGraphRepository()
    service = PlanningService(
        plans=plans,
        requirements=requirements,
        documents=documents,
        work_items=work_items,
        executions=executions,
        code_graph=code_graph,
    )
    return service, project


def _requirement(
    project_id, title: str, *, key: str | None = None, description: str = ""
) -> Requirement:
    return Requirement(
        project_id=project_id,
        key=key,
        title=title,
        description=description,
        acceptance_criteria=[AcceptanceCriterion(description="criterion present")],
        constraints=[Constraint(description="constraint")],
    )


async def test_ambiguity_assessment_flags_vague_requirement() -> None:
    service, project = _planning_service()
    await service._requirements.create(
        _requirement(
            project.id,
            "Make login faster",
            key="REQ-1",
            description="Handle it quickly",
        )
    )
    assessments = await service.assess(project.id)
    assert len(assessments) == 1
    assert assessments[0].clarity in {
        RequirementClarity.AMBIGUOUS,
        RequirementClarity.MISSING_INFO,
    }
    assert assessments[0].risk > 0


async def test_ambiguity_assessment_clear_requirement() -> None:
    service, project = _planning_service()
    await service._requirements.create(
        _requirement(
            project.id,
            "Support refresh token expiration",
            key="REQ-2",
            description="The refresh token MUST expire after fifteen minutes.",
        )
    )
    assessments = await service.assess(project.id)
    assert assessments[0].clarity == RequirementClarity.CLEAR
    assert assessments[0].risk < 0.5


async def test_decompose_produces_feature_story_task() -> None:
    service, project = _planning_service()
    await service._requirements.create(_requirement(project.id, "Login", key="REQ-1"))
    items = await service.decompose(project.id)
    types = {item.item_type for item in items}
    assert types == {PlanItemType.FEATURE, PlanItemType.STORY, PlanItemType.TASK}
    task = next(i for i in items if i.item_type == PlanItemType.TASK)
    assert task.acceptance_criteria == ["criterion present"]


async def test_extract_requirements_from_document() -> None:
    service, project = _planning_service()
    document = Document(
        project_id=project.id,
        title="Spec",
        source=DocumentSource(provider="git_markdown", uri="spec.md"),
    )
    await service._documents.create(document)
    version = DocumentVersion(document_id=document.id, checksum="v1")
    await service._documents.add_version(version)
    await service._documents.add_node(
        DocumentNode(
            version_id=version.id,
            node_type=DocumentNodeType.SECTION,
            title="Functional",
            heading_path=["Functional"],
            content="REQ-100 The system MUST support login.\nREQ-200 The system SHALL log out.",
        )
    )
    extracted = await service.extract_requirements(project.id)
    assert len(extracted) >= 2
    assert all(ext.source_refs for ext in extracted)
    assert any("support login" in ext.title.lower() for ext in extracted)


async def test_analyze_existing_classifies_status() -> None:
    service, project = _planning_service()
    await service._requirements.create(
        _requirement(project.id, "Implement user login", key="REQ-1")
    )
    repository_id = RepositoryId(uuid.uuid4())
    code_graph = InMemoryCodeGraphRepository()
    code_service = CodeIntelligenceService(parser=PythonAstParser(), repository=code_graph)
    await code_service.build_revision(
        repository_id,
        REVISION,
        {
            "app/login.py": "def login(uid):\n    return True\n",
            "tests/test_login.py": (
                "from app.login import login\ndef test_login():\n    assert login('u')\n"
            ),
        },
    )
    service._code_graph = code_graph
    items = await service.decompose(project.id)
    analyzed = await service.analyze_existing(repository_id, REVISION, items)
    login_tasks = [
        item
        for item in analyzed
        if item.item_type == PlanItemType.TASK and "login" in item.title.lower()
    ]
    assert login_tasks
    assert login_tasks[0].implementation_status in {
        ImplementationStatus.PARTIALLY_IMPLEMENTED,
        ImplementationStatus.IMPLEMENTED_BUT_UNVERIFIED,
    }


async def test_build_plan_reconciles_and_validates() -> None:
    service, project = _planning_service()
    await service._requirements.create(_requirement(project.id, "Login", key="REQ-1"))
    result = await service.build_plan(project.id, title="Auth plan")
    plan = result.plan
    assert plan.project_id == project.id
    assert plan.status == PlanStatus.VALIDATED
    assert plan.is_valid
    assert plan.evidence  # planning evidence recorded
    assert any("derives from" in e.note for e in plan.evidence)


async def test_build_plan_persists() -> None:
    service, project = _planning_service()
    await service._requirements.create(_requirement(project.id, "Login", key="REQ-1"))
    result = await service.build_plan(project.id, title="Auth plan", persist=True)
    stored = await service._plans.get_plan(result.plan.id)
    assert stored is not None
    assert stored.title == "Auth plan"


async def test_validation_detects_missing_criteria() -> None:
    service, project = _planning_service()
    requirement = _requirement(project.id, "Login", key="REQ-1")
    requirement.acceptance_criteria = []
    await service._requirements.create(requirement)
    plan = await service.build_plan(project.id, title="Auth plan")
    assert not plan.plan.is_valid
    assert any("acceptance criteria" in e for e in plan.plan.validation_errors)
