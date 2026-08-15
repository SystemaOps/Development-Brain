"""Unit tests for the Phase 10 context engine."""

from __future__ import annotations

import uuid

from brain.adapters.embeddings.hash_embedding import HashEmbeddingService
from brain.adapters.in_memory.code_graph import InMemoryCodeGraphRepository
from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryExecutionRepository,
    InMemoryRequirementRepository,
    InMemoryVerificationResultRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.semantic_index import InMemorySemanticIndex
from brain.application.context_engine import BudgetAllocator, ContextEngineService, ContextRanker
from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.jit_retrieval import JustInTimeRetrieval
from brain.application.token_estimation import TokenEstimator
from brain.domain.context import (
    ContextCandidate,
    ContextCategory,
    ContextRequest,
    ContextType,
)
from brain.domain.executions import Execution
from brain.domain.identity import new_actor_id, new_project_id, new_workflow_id
from brain.domain.requirements import Requirement
from brain.domain.verification import VerificationResult, VerificationVerdict
from brain.domain.work_items import WorkItem


def _engine() -> tuple[ContextEngineService, InMemoryWorkItemRepository]:
    work_items = InMemoryWorkItemRepository()
    requirements = InMemoryRequirementRepository()
    executions = InMemoryExecutionRepository()
    verification_results = InMemoryVerificationResultRepository()
    code_graph = InMemoryCodeGraphRepository()
    graph = InMemoryKnowledgeGraph()
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    capsules = InMemoryContextCapsuleRepository()
    engine = ContextEngineService(
        work_items=work_items,
        requirements=requirements,
        executions=executions,
        verification_results=verification_results,
        code_graph=code_graph,
        knowledge_graph=graph,
        retrieval=retrieval,
        capsules=capsules,
        token_estimator=TokenEstimator(),
    )
    return engine, work_items


async def test_engine_builds_coding_capsule() -> None:
    engine, work_items = _engine()
    work_item = WorkItem(project_id=new_project_id(), title="Implement login")
    await work_items.create(work_item)
    request = ContextRequest(work_item_id=work_item.id, context_type=ContextType.CODING)
    result = await engine.build(request)
    capsule = result.capsule
    assert capsule.context_type == ContextType.CODING
    assert capsule.work_item_id == work_item.id
    assert capsule.total_tokens > 0
    assert capsule.is_within_budget
    assert any(c.entity_type == "WorkItem" for c in capsule.candidates)
    assert any(c.entity_id == work_item.id for c in capsule.candidates)


async def test_engine_includes_requirements() -> None:
    engine, work_items = _engine()
    project_id = uuid.uuid4()
    requirement = Requirement(project_id=project_id, title="Login support", key="REQ-1")
    engine._requirements = InMemoryRequirementRepository()
    await engine._requirements.create(requirement)
    work_item = WorkItem(
        project_id=project_id,
        title="Implement login",
        requirement_refs=[requirement.id],
    )
    await work_items.create(work_item)
    request = ContextRequest(work_item_id=work_item.id, project_id=project_id)
    result = await engine.build(request)
    assert any(c.entity_type == "Requirement" for c in result.capsule.candidates)


async def test_engine_includes_history_and_verification_feedback() -> None:
    engine, work_items = _engine()
    project_id = uuid.uuid4()
    work_item = WorkItem(project_id=project_id, title="Fix token bug")
    await work_items.create(work_item)
    execution = Execution(
        workflow_id=new_workflow_id(), work_item_id=work_item.id, executor_id=new_actor_id()
    )
    await engine._executions.create(execution)
    await engine._verification_results.create(
        VerificationResult(execution_id=execution.id, verdict=VerificationVerdict.FAIL)
    )
    request = ContextRequest(work_item_id=work_item.id, project_id=project_id)
    result = await engine.build(request)
    entity_types = {c.entity_type for c in result.capsule.candidates}
    assert "Execution" in entity_types
    assert "VerificationResult" in entity_types


async def test_engine_persists_capsule() -> None:
    engine, work_items = _engine()
    work_item = WorkItem(project_id=new_project_id(), title="Task")
    await work_items.create(work_item)
    request = ContextRequest(work_item_id=work_item.id)
    result = await engine.build(request, persist=True)
    stored = await engine._capsules.get_capsule(result.capsule.id)
    assert stored is not None
    assert stored.id == result.capsule.id


async def test_budget_allocator_creates_categories() -> None:
    allocator = BudgetAllocator(8000)
    allocations = allocator.allocate(
        [
            ContextCandidate(
                entity_id=uuid.uuid4(),
                entity_type="WorkItem",
                content="x",
                category=ContextCategory.TASK,
            ),
            ContextCandidate(
                entity_id=uuid.uuid4(),
                entity_type="Symbol",
                content="y",
                category=ContextCategory.SOURCE_CODE,
            ),
        ]
    )
    categories = {a.category for a in allocations}
    assert ContextCategory.TASK in categories
    assert ContextCategory.SOURCE_CODE in categories
    total = sum(a.allocated_tokens for a in allocations)
    assert total <= 8000


async def test_rank_orders_by_relevance() -> None:
    high = ContextCandidate(
        entity_id=uuid.uuid4(),
        entity_type="Symbol",
        content="a",
        relevance_score=0.9,
    )
    low = ContextCandidate(
        entity_id=uuid.uuid4(),
        entity_type="Symbol",
        content="b",
        relevance_score=0.3,
    )
    ranked = ContextRanker().rank([low, high])
    assert ranked[0].entity_id == high.entity_id


async def test_engine_respects_budget_limits() -> None:
    engine, work_items = _engine()
    work_item = WorkItem(project_id=new_project_id(), title="Large task with lots of context")
    await work_items.create(work_item)
    request = ContextRequest(
        work_item_id=work_item.id, preferred_token_budget=400, max_total_tokens=500
    )
    result = await engine.build(request)
    assert result.capsule.total_tokens <= 500


async def test_jit_retrieval_search_project_knowledge() -> None:
    index = InMemorySemanticIndex(embeddings=HashEmbeddingService())
    graph = InMemoryKnowledgeGraph()
    retrieval = HybridRetrievalService(index=index, embeddings=HashEmbeddingService(), graph=graph)
    from brain.domain.knowledge import SemanticRecord

    await index.index(
        [
            SemanticRecord(
                entity_id=uuid.uuid4(),
                entity_type="DocumentNode",
                text="refresh token expires quickly",
            )
        ]
    )
    jit = JustInTimeRetrieval(
        code_graph=InMemoryCodeGraphRepository(),
        requirements=InMemoryRequirementRepository(),
        decisions=InMemoryDecisionRepository(),
        retrieval=retrieval,
    )
    results = await jit.search_project_knowledge("refresh token")
    assert any("refresh token" in c.content for c in results)
