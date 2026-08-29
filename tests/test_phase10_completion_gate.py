"""Phase 10 golden tests and completion gate.

The system can build a compact, explainable context capsule for a task WITHOUT
invoking a coding agent.  A task about "refresh token expiration" must include
the token service, config, and related tests, and exclude unrelated billing
code.
"""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.code_intelligence.python_ast import PythonAstParser
from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryDocumentRepository,
    InMemoryExecutionRepository,
    InMemoryRequirementRepository,
    InMemoryVerificationResultRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.application.code_intelligence import CodeIntelligenceService
from brain.application.context_engine import ContextEngineService
from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.semantic_indexing import SemanticIndexingService
from brain.application.token_estimation import TokenEstimator
from brain.domain.context import ContextCategory, ContextRequest, ContextType
from brain.domain.identity import RepositoryId
from brain.domain.projects import Project
from brain.domain.requirements import Requirement
from brain.domain.work_items import WorkItem

REVISION = "abc123"

REPOSITORY_FILES: dict[str, str] = {
    "app/token_service.py": """
def create_refresh_token(uid: str) -> str:
    "Creates a refresh token that expires quickly."
    return "token"

def validate_refresh_token(token: str) -> bool:
    return True
""",
    "config/settings.py": """
REFRESH_TOKEN_TTL_SECONDS = 900
""",
    "tests/test_token_service.py": """
from app.token_service import validate_refresh_token

def test_token_validates() -> None:
    assert validate_refresh_token("x")
""",
    "app/billing.py": """
def charge_card(amount: int) -> bool:
    return True
""",
}


@pytest.fixture
def index() -> InMemorySemanticIndex:
    return InMemorySemanticIndex(embeddings=HashEmbeddingService())


async def _build_engine(
    index: InMemorySemanticIndex,
) -> tuple[ContextEngineService, Project, WorkItem, RepositoryId]:
    project = Project(name="auth")
    work_items = InMemoryWorkItemRepository()
    requirements = InMemoryRequirementRepository()
    executions = InMemoryExecutionRepository()
    verification_results = InMemoryVerificationResultRepository()
    decisions = InMemoryDecisionRepository()
    code_graph = InMemoryCodeGraphRepository()
    graph = InMemoryKnowledgeGraph()

    requirement = Requirement(
        project_id=project.id,
        title="Support refresh token expiration",
        key="REQ-1",
    )
    await requirements.create(requirement)

    work_item = WorkItem(
        project_id=project.id,
        title="Change refresh token expiration",
        description="Reduce the refresh token TTL in the token service and its config.",
        requirement_refs=[requirement.id],
    )
    await work_items.create(work_item)

    # Index the repository code at the revision so the engine can search it.
    repository_id = RepositoryId(uuid.uuid4())
    code_service = CodeIntelligenceService(parser=PythonAstParser(), repository=code_graph)
    await code_service.build_revision(repository_id, REVISION, REPOSITORY_FILES)

    semantic_indexing = SemanticIndexingService(
        index=index,
        documents=InMemoryDocumentRepository(),
        requirements=requirements,
        decisions=decisions,
        code_graph=code_graph,
    )
    await semantic_indexing.index_project(
        project.id, repository_id=repository_id, revision=REVISION
    )

    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    engine = ContextEngineService(
        work_items=work_items,
        requirements=requirements,
        executions=executions,
        verification_results=verification_results,
        code_graph=code_graph,
        knowledge_graph=graph,
        retrieval=retrieval,
        capsules=InMemoryContextCapsuleRepository(),
        token_estimator=TokenEstimator(),
    )
    return engine, project, work_item, repository_id


async def test_gate_builds_capsule_without_coding_agent(index: InMemorySemanticIndex) -> None:
    engine, project, work_item, repository_id = await _build_engine(index)
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        repository_id=repository_id,
        revision=REVISION,
        context_type=ContextType.CODING,
        preferred_token_budget=8000,
    )
    result = await engine.build(request)
    capsule = result.capsule
    assert capsule.is_within_budget
    assert capsule.total_tokens <= capsule.model_budget_tokens
    assert result.candidates_gathered > 0
    assert result.candidates_included > 0


async def test_gate_includes_token_service(index: InMemorySemanticIndex) -> None:
    engine, project, work_item, repository_id = await _build_engine(index)
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        repository_id=repository_id,
        revision=REVISION,
    )
    result = await engine.build(request)
    content = "\n".join(c.content for c in result.capsule.candidates).lower()
    assert "token" in content


async def test_gate_includes_related_test(index: InMemorySemanticIndex) -> None:
    engine, project, work_item, repository_id = await _build_engine(index)
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        repository_id=repository_id,
        revision=REVISION,
    )
    result = await engine.build(request)
    test_candidates = [c for c in result.capsule.candidates if c.category == ContextCategory.TESTS]
    assert any("test_token_service" in c.content for c in test_candidates)


async def test_gate_budget_allocation_has_categories(index: InMemorySemanticIndex) -> None:
    engine, project, work_item, repository_id = await _build_engine(index)
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        repository_id=repository_id,
        revision=REVISION,
        preferred_token_budget=8000,
    )
    result = await engine.build(request)
    categories = {a.category for a in result.capsule.allocations}
    assert ContextCategory.TASK in categories
    assert ContextCategory.REQUIREMENTS in categories
    assert ContextCategory.SOURCE_CODE in categories


async def test_gate_capsule_is_persisted(index: InMemorySemanticIndex) -> None:
    engine, project, work_item, repository_id = await _build_engine(index)
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        repository_id=repository_id,
        revision=REVISION,
    )
    result = await engine.build(request, persist=True)
    stored = await engine._capsules.get_capsule(result.capsule.id)
    assert stored is not None
    assert stored.revision == REVISION


async def test_gate_capsule_is_explainable(index: InMemorySemanticIndex) -> None:
    engine, project, work_item, repository_id = await _build_engine(index)
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        repository_id=repository_id,
        revision=REVISION,
    )
    result = await engine.build(request)
    for candidate in result.capsule.candidates:
        assert candidate.reason, f"candidate {candidate.entity_type} lacks a reason"
        assert candidate.relevance_score >= 0


async def test_gate_compact_capsule_for_small_budget(index: InMemorySemanticIndex) -> None:
    engine, project, work_item, repository_id = await _build_engine(index)
    request = ContextRequest(
        work_item_id=work_item.id,
        project_id=project.id,
        repository_id=repository_id,
        revision=REVISION,
        preferred_token_budget=800,
        max_total_tokens=1000,
    )
    result = await engine.build(request)
    assert result.capsule.total_tokens <= 1000
    assert result.capsule.is_within_budget
