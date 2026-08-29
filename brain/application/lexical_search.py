"""Lexical search service (Task 9.6).

BM25-like scoring over indexed records so hybrid retrieval never depends on
semantic search alone.  Operates on :class:`SemanticRecord` text (index layer),
but is purely lexical and deterministic.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from brain.domain.knowledge import SemanticRecord

_WORD_SPLIT = re.compile(r"\W+")


def tokenize(text: str) -> list[str]:
    return [t for t in _WORD_SPLIT.split(text.lower()) if t]


class LexicalSearchService:
    """BM25 scoring over a corpus of records."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b

    def search(
        self,
        corpus: list[SemanticRecord],
        query: str,
        limit: int = 10,
    ) -> list[tuple[SemanticRecord, float]]:
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
                tf_norm = (tf * (self._k1 + 1)) / (
                    tf + self._k1 * (1 - self._b + self._b * dl / avgdl)
                )
                score += idf * tf_norm
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(record, score) for score, record in scored[:limit]]


__all__ = ["LexicalSearchService", "tokenize"]
