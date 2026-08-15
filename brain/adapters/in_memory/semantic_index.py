"""In-memory semantic index reference implementation.

Lexical search uses real BM25 scoring; vector search uses cosine similarity
against per-record embeddings produced by an injected embedding service.  This
is the reference behavior the Weaviate adapter must match.
"""

from __future__ import annotations

import math
import re
import threading
import uuid
from collections import Counter

from brain.application.lexical_search import tokenize
from brain.domain.knowledge import SemanticRecord
from brain.ports.embeddings import EmbeddingService

_WORD_SPLIT = re.compile(r"\W+")


class InMemorySemanticIndex:
    def __init__(
        self,
        *,
        embeddings: EmbeddingService | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._lock = threading.RLock()
        self._records: dict[uuid.UUID, SemanticRecord] = {}
        self._embeddings = embeddings

    async def index(self, records: list[SemanticRecord]) -> None:
        with self._lock:
            for record in records:
                self._records[record.record_id] = record

    async def delete(self, ids: list[uuid.UUID]) -> None:
        with self._lock:
            for record_id in ids:
                self._records.pop(record_id, None)

    async def search(
        self, query: str, filters: dict[str, object], limit: int
    ) -> list[SemanticRecord]:
        with self._lock:
            corpus = [r for r in self._records.values() if _matches_filters(r, filters)]
        scored = self._bm25(corpus, query)
        return [record for _, record in scored[:limit]]

    async def search_by_vector(
        self,
        vector: list[float],
        filters: dict[str, object],
        limit: int,
    ) -> list[SemanticRecord]:
        if self._embeddings is None:
            raise RuntimeError("search_by_vector requires an embedding service")
        with self._lock:
            corpus = [r for r in self._records.values() if _matches_filters(r, filters)]
        # Compute embeddings for the corpus (deterministic) and score by cosine.
        texts = [record.text for record in corpus]
        vectors = await self._embeddings.embed(texts)
        scored: list[tuple[float, SemanticRecord]] = []
        for record, record_vector in zip(corpus, vectors, strict=True):
            score = _cosine(vector, record_vector)
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [record for _, record in scored[:limit]]

    def _bm25(self, corpus: list[SemanticRecord], query: str) -> list[tuple[float, SemanticRecord]]:
        if not corpus:
            return []
        query_terms = tokenize(query)
        if not query_terms:
            return []
        avgdl = sum(len(tokenize(record.text)) for record in corpus) / len(corpus)
        n = len(corpus)
        doc_freqs: Counter[str] = Counter()
        term_counts: list[Counter[str]] = []
        for record in corpus:
            counts = Counter(tokenize(record.text))
            term_counts.append(counts)
            for term in set(counts):
                doc_freqs[term] += 1
        k1, b = 1.5, 0.75
        scored: list[tuple[float, SemanticRecord]] = []
        for record, counts in zip(corpus, term_counts, strict=True):
            dl = sum(counts.values())
            score = 0.0
            for term in query_terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                df = doc_freqs.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
                score += idf * tf_norm
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored


def _matches_filters(record: SemanticRecord, filters: dict[str, object]) -> bool:
    project = filters.get("project_id")
    repository = filters.get("repository_id")
    revision = filters.get("revision")
    entity_type = filters.get("entity_type")
    return (
        (project is None or record.project_id == project)
        and (repository is None or record.repository_id == repository)
        and (revision is None or record.revision == revision)
        and (entity_type is None or record.entity_type == entity_type)
    )


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
