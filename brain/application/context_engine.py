"""Context engine service (Phase 10).

Constructs precise, bounded task context from many sources without invoking a
coding agent.  Pipeline:

1. :meth:`ContextEngineService.build` gathers :class:`ContextCandidate` items
   from the work item, its requirements, the knowledge graph, the code graph,
   semantic + lexical search, git history (past executions), and verification
   feedback.
2. A pluggable ranker scores them deterministically.
3. The budget allocator fills per-category token budgets.
4. The result is a persistent :class:`ContextCapsule` with explainable reasons.

Everything depends only on ports + domain, so it runs against in-memory
references or real adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.application.impact_analysis import ImpactAnalysisService
from brain.application.token_estimation import TokenEstimator
from brain.domain.code_intelligence import Symbol, is_test_path
from brain.domain.context import (
    BudgetAllocation,
    CodingContextCapsule,
    ContextCandidate,
    ContextCapsule,
    ContextCategory,
    ContextRequest,
    ContextType,
    PlanningContextCapsule,
    RetrievalSource,
    VerificationContextCapsule,
)
from brain.domain.graph_schema import GraphLabel
from brain.domain.identity import WorkItemId
from brain.domain.requirements import Requirement
from brain.domain.work_items import WorkItem
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.context import ContextCapsuleRepository
from brain.ports.knowledge_graph import GraphEntity, KnowledgeGraphRepository
from brain.ports.repositories import (
    ExecutionRepository,
    RequirementRepository,
    VerificationResultRepository,
    WorkItemRepository,
)


@dataclass
class BuildResult:
    capsule: ContextCapsule
    candidates_gathered: int = 0
    candidates_included: int = 0


class ContextEngineService:
    """Build compact, explainable context capsules for a task."""

    def __init__(
        self,
        *,
        work_items: WorkItemRepository,
        requirements: RequirementRepository,
        executions: ExecutionRepository,
        verification_results: VerificationResultRepository,
        code_graph: CodeGraphRepository,
        knowledge_graph: KnowledgeGraphRepository,
        retrieval: HybridRetrievalService,
        capsules: ContextCapsuleRepository,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        self._work_items = work_items
        self._requirements = requirements
        self._executions = executions
        self._verification_results = verification_results
        self._code_graph = code_graph
        self._knowledge_graph = knowledge_graph
        self._retrieval = retrieval
        self._capsules = capsules
        self._token_estimator = token_estimator or TokenEstimator()

    async def build(
        self,
        request: ContextRequest,
        *,
        persist: bool = True,
    ) -> BuildResult:
        work_item = await self._work_items.get(request.work_item_id)
        candidates = await self._gather_candidates(request, work_item)

        ranker = ContextRanker()
        ranked = ranker.rank(candidates)

        allocator = BudgetAllocator(request.preferred_token_budget)
        allocations = allocator.allocate(ranked)

        capsule = self._build_capsule(request, ranked, allocations)
        if persist:
            await self._capsules.save_capsule(capsule)
        return BuildResult(
            capsule=capsule,
            candidates_gathered=len(candidates),
            candidates_included=len(capsule.candidates),
        )

    async def _gather_candidates(
        self, request: ContextRequest, work_item: WorkItem | None
    ) -> list[ContextCandidate]:
        candidates: list[ContextCandidate] = []
        query_text = _work_item_text(work_item, request.work_item_id)

        # 1. Work item itself.
        candidates.append(
            ContextCandidate(
                entity_id=request.work_item_id,
                entity_type="WorkItem",
                content=query_text,
                reason="primary task",
                retrieval_source=RetrievalSource.WORK_ITEM,
                relevance_score=1.0,
                trust_score=1.0,
                category=ContextCategory.TASK,
            )
        )

        # 2. Requirements referenced by the work item.
        if work_item is not None:
            for requirement_id in work_item.requirement_refs:
                requirement = await self._requirements.get(requirement_id)
                if requirement is None:
                    continue
                candidates.append(
                    ContextCandidate(
                        entity_id=requirement.id,
                        entity_type="Requirement",
                        content=_requirement_text(requirement),
                        reason="requirement referenced by task",
                        retrieval_source=RetrievalSource.REQUIREMENT,
                        relevance_score=0.95,
                        trust_score=0.9,
                        category=ContextCategory.REQUIREMENTS,
                    )
                )

        # 3. Semantic + lexical search over project knowledge.
        if request.project_id is not None:
            search_candidates = await self._retrieval.retrieve(
                query_text,
                project_id=request.project_id,
                repository_id=request.repository_id,
                revision=request.revision,
                limit=20,
            )
            for hit in search_candidates:
                candidates.append(
                    ContextCandidate(
                        entity_id=hit.record.entity_id,
                        entity_type=hit.record.entity_type,
                        content=hit.record.text,
                        reason=hit.reason,
                        retrieval_source=RetrievalSource.SEMANTIC_SEARCH
                        if hit.retrieval_source == "semantic"
                        else RetrievalSource.LEXICAL_SEARCH,
                        relevance_score=hit.relevance_score,
                        trust_score=hit.trust_score,
                        category=_category_for_entity_type(hit.record.entity_type),
                    )
                )

        # 4. Code graph: symbols in the repository at the revision.
        if request.repository_id is not None and request.revision is not None:
            symbols = await self._code_graph.list_symbols(request.repository_id, request.revision)
            impact = ImpactAnalysisService(repository=self._code_graph)
            impact_result = await impact.analyze(
                request.repository_id,
                request.revision,
                target_symbols=[],
                task_concepts=_concepts(query_text),
            )
            for symbol in symbols:
                category = (
                    ContextCategory.TESTS
                    if is_test_path(symbol.path)
                    else ContextCategory.SOURCE_CODE
                )
                candidates.append(
                    ContextCandidate(
                        entity_id=symbol.id,
                        entity_type="Symbol",
                        content=_symbol_text(symbol),
                        reason=_symbol_reason(symbol, impact_result.related_files),
                        retrieval_source=RetrievalSource.CODE_GRAPH,
                        relevance_score=_symbol_score(symbol, query_text),
                        trust_score=0.8,
                        category=category,
                        metadata={
                            "qualified_name": symbol.qualified_name,
                            "path": symbol.path,
                        },
                    )
                )

        # 5. History: previous executions for this work item.
        if request.include_history:
            for execution in await self._executions.list_by_work_item(request.work_item_id):
                content = f"Execution {execution.id}: status={execution.status.value}"
                if execution.completed_at:
                    content += f" completed_at={execution.completed_at.isoformat()}"
                candidates.append(
                    ContextCandidate(
                        entity_id=execution.id,
                        entity_type="Execution",
                        content=content,
                        reason="previous execution history",
                        retrieval_source=RetrievalSource.GIT_HISTORY,
                        relevance_score=0.5,
                        trust_score=0.7,
                        category=ContextCategory.HISTORY,
                    )
                )
                if request.include_verification_feedback:
                    for result in await self._verification_results.list_by_execution(execution.id):
                        candidates.append(
                            ContextCandidate(
                                entity_id=result.id,
                                entity_type="VerificationResult",
                                content=f"Verification {result.id}: verdict={result.verdict}",
                                reason="verification feedback",
                                retrieval_source=RetrievalSource.VERIFICATION_FEEDBACK,
                                relevance_score=0.6,
                                trust_score=0.9,
                                category=ContextCategory.TESTS,
                            )
                        )

        # 6. Knowledge graph neighborhood around the work item.
        if request.project_id is not None:
            graph_entities = await self._knowledge_graph.find_entities(
                project_id=request.project_id
            )
            for entity in graph_entities:
                if entity.label in {
                    GraphLabel.DECISION,
                    GraphLabel.REQUIREMENT,
                    GraphLabel.COMPONENT,
                }:
                    candidates.append(
                        ContextCandidate(
                            entity_id=entity.id,
                            entity_type=entity.label.value,
                            content=_entity_text(entity),
                            reason="knowledge graph entity",
                            retrieval_source=RetrievalSource.KNOWLEDGE_GRAPH,
                            relevance_score=0.5,
                            trust_score=0.6,
                            category=ContextCategory.ARCHITECTURE,
                        )
                    )

        return candidates

    def _build_capsule(
        self,
        request: ContextRequest,
        ranked: list[ContextCandidate],
        allocations: list[BudgetAllocation],
    ) -> ContextCapsule:
        included: list[ContextCandidate] = []
        total = 0
        model_budget = request.max_total_tokens
        used_by_category: dict[ContextCategory, int] = {}
        for candidate in ranked:
            category = candidate.category
            allocation = next((a for a in allocations if a.category == category), None)
            if allocation is not None and allocation.remaining <= 0:
                continue
            estimate = self._token_estimator.estimate(candidate.content)
            candidate.token_estimate = estimate
            if total + estimate > model_budget:
                break
            included.append(candidate)
            total += estimate
            used_by_category[category] = used_by_category.get(category, 0) + estimate
            if allocation is not None:
                allocation.used_tokens += estimate

        if request.context_type == ContextType.PLANNING:
            capsule: ContextCapsule = PlanningContextCapsule(
                work_item_id=request.work_item_id,
                request=request,
                repository_id=request.repository_id,
                revision=request.revision,
                candidates=included,
                allocations=allocations,
                total_tokens=total,
                model_budget_tokens=model_budget,
            )
        elif request.context_type == ContextType.VERIFICATION:
            capsule = VerificationContextCapsule(
                work_item_id=request.work_item_id,
                request=request,
                repository_id=request.repository_id,
                revision=request.revision,
                candidates=included,
                allocations=allocations,
                total_tokens=total,
                model_budget_tokens=model_budget,
            )
        else:
            capsule = CodingContextCapsule(
                work_item_id=request.work_item_id,
                request=request,
                repository_id=request.repository_id,
                revision=request.revision,
                candidates=included,
                allocations=allocations,
                total_tokens=total,
                model_budget_tokens=model_budget,
            )
        return capsule


class ContextRanker:
    """Deterministic relevance ranking (Task 10.4).

    Pluggable: replace this class to change the scoring function.
    """

    def rank(self, candidates: list[ContextCandidate]) -> list[ContextCandidate]:
        scored = sorted(
            candidates,
            key=lambda c: (
                c.relevance_score,
                c.trust_score,
                c.freshness,
                -c.token_estimate,
            ),
            reverse=True,
        )
        return scored


class BudgetAllocator:
    """Per-category token allocation (Task 10.6)."""

    _DEFAULT_WEIGHTS: dict[ContextCategory, float] = {
        ContextCategory.TASK: 0.15,
        ContextCategory.REQUIREMENTS: 0.15,
        ContextCategory.ARCHITECTURE: 0.15,
        ContextCategory.SOURCE_CODE: 0.30,
        ContextCategory.TESTS: 0.10,
        ContextCategory.HISTORY: 0.05,
        ContextCategory.INSTRUCTIONS: 0.10,
    }

    def __init__(self, total_budget: int) -> None:
        self._total = total_budget

    def allocate(self, candidates: list[ContextCandidate]) -> list[BudgetAllocation]:
        present = {c.category for c in candidates}
        allocations: list[BudgetAllocation] = []
        for category, weight in self._DEFAULT_WEIGHTS.items():
            if category in present:
                allocations.append(
                    BudgetAllocation(
                        category=category,
                        allocated_tokens=int(self._total * weight),
                    )
                )
        return allocations


def _work_item_text(work_item: WorkItem | None, work_item_id: WorkItemId) -> str:
    if work_item is None:
        return f"work item {work_item_id}"
    return f"{work_item.title}\n{work_item.description}".strip()


def _requirement_text(requirement: Requirement) -> str:
    return f"{requirement.key or ''}: {requirement.title}\n{requirement.description}".strip()


def _symbol_text(symbol: Symbol) -> str:
    parts = [symbol.qualified_name]
    if symbol.parameters:
        parts.append("(" + ", ".join(symbol.parameters) + ")")
    if symbol.return_annotation:
        parts.append(f" -> {symbol.return_annotation}")
    if symbol.docstring:
        parts.append(symbol.docstring)
    return " ".join(parts)


def _symbol_reason(symbol: Symbol, related_files: list[str]) -> str:
    if symbol.path in related_files:
        return "contains primary impacted symbol"
    return "symbol in repository at revision"


def _symbol_score(symbol: Symbol, query_text: str) -> float:
    lowered = query_text.lower()
    score = 0.3
    if symbol.name.lower() in lowered or symbol.qualified_name.lower() in lowered:
        score = 0.9
    elif symbol.docstring and any(
        word in symbol.docstring.lower() for word in _concepts(query_text)
    ):
        score = 0.6
    return score


def _concepts(text: str) -> list[str]:
    return [word for word in text.lower().split() if len(word) > 2]


def _entity_text(entity: GraphEntity) -> str:
    parts = [str(entity.label.value)]
    for key in ("name", "path", "title"):
        if entity.properties.get(key):
            parts.append(str(entity.properties[key]))
    return " ".join(parts)


def _category_for_entity_type(entity_type: str) -> ContextCategory:
    lowered = entity_type.lower()
    if lowered == "documentnode":
        return ContextCategory.ARCHITECTURE
    if lowered == "requirement":
        return ContextCategory.REQUIREMENTS
    if lowered == "decision":
        return ContextCategory.ARCHITECTURE
    if lowered == "symbol":
        return ContextCategory.SOURCE_CODE
    return ContextCategory.SOURCE_CODE


__all__ = [
    "BudgetAllocator",
    "BuildResult",
    "ContextEngineService",
    "ContextRanker",
]
