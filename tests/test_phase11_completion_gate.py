"""Phase 11 golden tests and completion gate.

Given a HALF-FINISHED project (some requirements implemented, others not) and a
requirements document, the system produces an updated plan reflecting the
actual implementation status: implemented work is skipped or marked, remaining
work is planned with dependencies, acceptance criteria, and evidence linking
tasks to requirements.
"""

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
from brain.domain.planning import ImplementationStatus, PlanItemType
from brain.domain.projects import Project
from brain.domain.requirements import AcceptanceCriterion, Requirement

REVISION = "abc123"

# The repository: login IS implemented with tests; billing is NOT implemented.
REPOSITORY_FILES: dict[str, str] = {
    "app/login.py": """
def login(uid: str) -> bool:
    return True
""",
    "tests/test_login.py": """
from app.login import login

def test_login() -> None:
    assert login("u")
""",
}

REQUIREMENTS_DOC = """# Requirements

REQ-1 The system MUST support user login.
REQ-2 The system SHALL support credit card billing.
"""


async def _seed_half_finished_project() -> tuple[PlanningService, Project, RepositoryId]:
    project = Project(name="auth")
    plans = InMemoryPlanRepository()
    requirements = InMemoryRequirementRepository()
    documents = InMemoryDocumentRepository()
    work_items = InMemoryWorkItemRepository()
    executions = InMemoryExecutionRepository()
    code_graph = InMemoryCodeGraphRepository()

    # Login requirement with acceptance criteria; billing requirement too.
    login_req = Requirement(
        project_id=project.id,
        key="REQ-1",
        title="Support user login",
        description="The system MUST support user login.",
        acceptance_criteria=[AcceptanceCriterion(description="login works")],
    )
    billing_req = Requirement(
        project_id=project.id,
        key="REQ-2",
        title="Support credit card billing",
        description="The system SHALL support credit card billing.",
        acceptance_criteria=[AcceptanceCriterion(description="billing works")],
    )
    await requirements.create(login_req)
    await requirements.create(billing_req)

    # Requirements document for extraction.
    document = Document(
        project_id=project.id,
        title="Requirements",
        source=DocumentSource(provider="git_markdown", uri="docs/requirements.md"),
    )
    await documents.create(document)
    version = DocumentVersion(document_id=document.id, checksum="v1")
    await documents.add_version(version)
    await documents.add_node(
        DocumentNode(
            version_id=version.id,
            node_type=DocumentNodeType.SECTION,
            title="Requirements",
            heading_path=["Requirements"],
            content=REQUIREMENTS_DOC,
        )
    )

    # Code graph at the revision (login implemented, billing missing).
    repository_id = RepositoryId(uuid.uuid4())
    code_service = CodeIntelligenceService(parser=PythonAstParser(), repository=code_graph)
    await code_service.build_revision(repository_id, REVISION, REPOSITORY_FILES)

    service = PlanningService(
        plans=plans,
        requirements=requirements,
        documents=documents,
        work_items=work_items,
        executions=executions,
        code_graph=code_graph,
    )
    return service, project, repository_id


async def test_gate_produces_updated_plan_with_status() -> None:
    service, project, repository_id = await _seed_half_finished_project()
    result = await service.build_plan(
        project.id,
        title="Updated plan",
        repository_id=repository_id,
        revision=REVISION,
    )
    plan = result.plan
    assert plan.items

    # Login task should be recognized as implemented or partially implemented;
    # billing task should be NOT_IMPLEMENTED.
    login_task = next(
        (
            item
            for item in plan.items
            if item.item_type == PlanItemType.TASK and "login" in item.title.lower()
        ),
        None,
    )
    billing_task = next(
        (
            item
            for item in plan.items
            if item.item_type == PlanItemType.TASK and "billing" in item.title.lower()
        ),
        None,
    )

    assert login_task is not None
    assert login_task.implementation_status in {
        ImplementationStatus.PARTIALLY_IMPLEMENTED,
        ImplementationStatus.IMPLEMENTED,
        ImplementationStatus.IMPLEMENTED_BUT_UNVERIFIED,
    }

    assert billing_task is not None
    assert billing_task.implementation_status == ImplementationStatus.NOT_IMPLEMENTED


async def test_gate_plan_is_validated_and_has_evidence() -> None:
    service, project, repository_id = await _seed_half_finished_project()
    result = await service.build_plan(
        project.id,
        title="Updated plan",
        repository_id=repository_id,
        revision=REVISION,
    )
    plan = result.plan
    assert plan.is_valid
    assert plan.status.value == "validated"
    assert plan.evidence
    assert all(e.plan_id == plan.id for e in plan.evidence)


async def test_gate_plan_persists_for_later_evaluation() -> None:
    service, project, repository_id = await _seed_half_finished_project()
    result = await service.build_plan(
        project.id,
        title="Updated plan",
        repository_id=repository_id,
        revision=REVISION,
        persist=True,
    )
    stored = await service._plans.get_plan(result.plan.id)
    assert stored is not None
    assert stored.title == "Updated plan"
    assert len(stored.items) == len(result.plan.items)


async def test_gate_assessments_flag_requirements() -> None:
    service, project, repository_id = await _seed_half_finished_project()
    result = await service.build_plan(
        project.id,
        title="Updated plan",
        repository_id=repository_id,
        revision=REVISION,
    )
    assert result.requirements_extracted >= 2
    assert len(result.plan.assessments) >= 2


async def test_gate_extraction_retains_provenance() -> None:
    service, project, _ = await _seed_half_finished_project()
    extracted = await service.extract_requirements(project.id)
    assert extracted
    assert all(ext.source_refs for ext in extracted)
    assert any("login" in ext.title.lower() for ext in extracted)
