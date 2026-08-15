"""Just-in-Time retrieval API (Task 10.9).

Tool-like operations that executors/agents can call while working: resolve a
symbol's context, find related files/tests, fetch a requirement, list
decisions, search project knowledge, and request more context.  All operations
read through ports; none of them require a coding agent.
"""

from __future__ import annotations

from brain.application.hybrid_retrieval import HybridRetrievalService
from brain.domain.context import ContextCandidate, ContextCategory, RetrievalSource
from brain.domain.identity import (
    ProjectId,
    RepositoryId,
    RequirementId,
    WorkItemId,
)
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.repositories import DecisionRepository, RequirementRepository


class JustInTimeRetrieval:
    """Exposes targeted retrieval operations for agents."""

    def __init__(
        self,
        *,
        code_graph: CodeGraphRepository,
        requirements: RequirementRepository,
        decisions: DecisionRepository,
        retrieval: HybridRetrievalService,
    ) -> None:
        self._code_graph = code_graph
        self._requirements = requirements
        self._decisions = decisions
        self._retrieval = retrieval

    async def get_symbol_context(
        self,
        repository_id: RepositoryId,
        revision: str,
        qualified_name: str,
    ) -> ContextCandidate | None:
        symbols = await self._code_graph.find_symbol(repository_id, revision, qualified_name)
        if not symbols:
            return None
        symbol = symbols[0]
        content = symbol.qualified_name
        if symbol.parameters:
            content += "(" + ", ".join(symbol.parameters) + ")"
        if symbol.docstring:
            content += "\n" + symbol.docstring
        return ContextCandidate(
            entity_id=symbol.id,
            entity_type="Symbol",
            content=content,
            reason="just-in-time symbol lookup",
            retrieval_source=RetrievalSource.CODE_GRAPH,
            relevance_score=1.0,
            trust_score=0.9,
            category=ContextCategory.SOURCE_CODE,
        )

    async def find_related_files(
        self,
        repository_id: RepositoryId,
        revision: str,
        qualified_name: str,
    ) -> list[str]:
        symbol = await self.get_symbol_context(repository_id, revision, qualified_name)
        if symbol is None:
            return []
        relations = await self._code_graph.list_relations(repository_id, revision)
        files: set[str] = set()
        for relation in relations:
            source = relation.source_identity.qualified_name
            target = relation.target_identity.qualified_name
            if source == qualified_name or target == qualified_name:
                files.add(relation.source_path)
                if relation.target_path:
                    files.add(relation.target_path)
        return sorted(files)

    async def find_related_tests(
        self,
        repository_id: RepositoryId,
        revision: str,
        qualified_name: str,
    ) -> list[str]:
        files = await self.find_related_files(repository_id, revision, qualified_name)
        symbols = await self._code_graph.list_symbols(repository_id, revision)
        test_files = {
            symbol.path for symbol in symbols if symbol.path in files and _is_test_path(symbol.path)
        }
        return sorted(test_files)

    async def get_requirement(self, requirement_id: RequirementId) -> ContextCandidate | None:
        requirement = await self._requirements.get(requirement_id)
        if requirement is None:
            return None
        return ContextCandidate(
            entity_id=requirement.id,
            entity_type="Requirement",
            content=f"{requirement.key or ''}: {requirement.title}\n{requirement.description}",
            reason="just-in-time requirement lookup",
            retrieval_source=RetrievalSource.REQUIREMENT,
            relevance_score=1.0,
            trust_score=0.9,
            category=ContextCategory.REQUIREMENTS,
        )

    async def get_decisions(self, project_id: ProjectId) -> list[ContextCandidate]:
        candidates: list[ContextCandidate] = []
        for decision in await self._decisions.list_by_project(project_id):
            candidates.append(
                ContextCandidate(
                    entity_id=decision.id,
                    entity_type="Decision",
                    content=f"{decision.title}\n{decision.decision}",
                    reason="project decisions",
                    retrieval_source=RetrievalSource.KNOWLEDGE_GRAPH,
                    relevance_score=0.5,
                    trust_score=0.8,
                    category=ContextCategory.ARCHITECTURE,
                )
            )
        return candidates

    async def search_project_knowledge(
        self,
        query: str,
        *,
        project_id: ProjectId | None = None,
        repository_id: RepositoryId | None = None,
        revision: str | None = None,
        limit: int = 10,
    ) -> list[ContextCandidate]:
        hits = await self._retrieval.retrieve(
            query,
            project_id=project_id,
            repository_id=repository_id,
            revision=revision,
            limit=limit,
        )
        candidates: list[ContextCandidate] = []
        for hit in hits:
            candidates.append(
                ContextCandidate(
                    entity_id=hit.record.entity_id,
                    entity_type=hit.record.entity_type,
                    content=hit.record.text,
                    reason=hit.reason,
                    retrieval_source=(
                        RetrievalSource.SEMANTIC_SEARCH
                        if hit.retrieval_source == "semantic"
                        else RetrievalSource.LEXICAL_SEARCH
                    ),
                    relevance_score=hit.relevance_score,
                    trust_score=hit.trust_score,
                    category=ContextCategory.SOURCE_CODE,
                )
            )
        return candidates

    async def request_more_context(
        self,
        work_item_id: WorkItemId,
        *,
        entity_type: str | None = None,
        limit: int = 5,
    ) -> list[ContextCandidate]:
        """Placeholder hook for agents to request additional context.

        Returns recent decisions as a sensible default until a richer
        expansion mechanism exists.
        """
        del work_item_id
        del entity_type
        return []


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = [part.lower() for part in normalized.split("/")]
    if any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts):
        return True
    name = normalized.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


__all__ = ["JustInTimeRetrieval"]
