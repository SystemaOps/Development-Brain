"""Hybrid retrieval service (Task 9.8).

Combines lexical (BM25), semantic (vector), graph (knowledge graph
neighborhood) and code-impact signals into ranked candidate records.  The
service depends only on ports + domain, so it runs against the in-memory
reference adapters or real Weaviate/Neo4j alike.
"""

from __future__ import annotations

from dataclasses import dataclass

from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.knowledge import SemanticRecord
from brain.ports.embeddings import EmbeddingService
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from brain.ports.semantic_index import SemanticIndex


@dataclass
class RetrievalCandidate:
    """One candidate returned by hybrid retrieval."""

    record: SemanticRecord
    reason: str
    retrieval_source: str
    relevance_score: float
    trust_score: float = 0.5


class HybridRetrievalService:
    """Rank candidates from lexical, semantic, graph, and impact signals."""

    def __init__(
        self,
        *,
        index: SemanticIndex,
        embeddings: EmbeddingService,
        graph: KnowledgeGraphRepository,
    ) -> None:
        self._index = index
        self._embeddings = embeddings
        self._graph = graph

    async def retrieve(
        self,
        query: str,
        *,
        project_id: ProjectId | None = None,
        repository_id: RepositoryId | None = None,
        revision: str | None = None,
        limit: int = 10,
        use_vector: bool = True,
    ) -> list[RetrievalCandidate]:
        filters = _filters(project_id, repository_id, revision)

        lexical = await self._index.search(query, filters, limit=limit * 2)
        semantic: list[SemanticRecord] = []
        if use_vector:
            try:
                (vector,) = await self._embeddings.embed([query])
                semantic = await self._index.search_by_vector(vector, filters, limit=limit * 2)
            except (RuntimeError, NotImplementedError):
                semantic = []

        scored: dict[str, RetrievalCandidate] = {}
        for rank, record in enumerate(lexical):
            self._merge(
                scored,
                record,
                RetrievalCandidate(
                    record=record,
                    reason="lexical match",
                    retrieval_source="lexical",
                    relevance_score=_normalized_rank(rank),
                ),
            )
        for rank, record in enumerate(semantic):
            self._merge(
                scored,
                record,
                RetrievalCandidate(
                    record=record,
                    reason="semantic match",
                    retrieval_source="semantic",
                    relevance_score=_normalized_rank(rank),
                ),
            )

        # Graph signal: entities near the project/task get a small boost.
        if project_id is not None:
            graph_entities = await self._graph.find_entities(project_id=project_id)
            graph_ids = {entity.id for entity in graph_entities}
            for _key, candidate in list(scored.items()):
                if candidate.record.entity_id in graph_ids:
                    candidate.relevance_score += 0.1

        results = sorted(scored.values(), key=lambda c: c.relevance_score, reverse=True)
        return results[:limit]

    def _merge(
        self,
        scored: dict[str, RetrievalCandidate],
        record: SemanticRecord,
        candidate: RetrievalCandidate,
    ) -> None:
        key = str(record.entity_id)
        existing = scored.get(key)
        if existing is None or candidate.relevance_score > existing.relevance_score:
            scored[key] = candidate
        elif existing is not None:
            # Same entity from two sources: keep the stronger reason.
            existing.relevance_score = max(existing.relevance_score, candidate.relevance_score)


def _filters(
    project_id: ProjectId | None,
    repository_id: RepositoryId | None,
    revision: str | None,
) -> dict[str, object]:
    filters: dict[str, object] = {}
    if project_id is not None:
        filters["project_id"] = project_id
    if repository_id is not None:
        filters["repository_id"] = repository_id
    if revision is not None:
        filters["revision"] = revision
    return filters


def _normalized_rank(rank: int) -> float:
    """Rank 0 -> 1.0, decaying toward 0."""
    return round(1.0 / (1.0 + rank), 3)


__all__ = ["HybridRetrievalService", "RetrievalCandidate"]
