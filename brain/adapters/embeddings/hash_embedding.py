"""Deterministic local embedding service (Task 9.5).

A hashing-based embedding that is deterministic, offline, and dependency-free:
the same text always produces the same vector.  Useful for contract tests, the
in-memory reference index, and as a placeholder behind the embedding port until
a remote model (or a local transformer) is configured.  It is deliberately
simple -- token n-gram hashing -- not a learned embedding.
"""

from __future__ import annotations

import hashlib
import re

_WORD_SPLIT = re.compile(r"\W+")


class HashEmbeddingService:
    """N-gram hashing embedding with L2 normalization."""

    def __init__(self, dimensions: int = 256, ngram: int = 2) -> None:
        self._dimensions = dimensions
        self._ngram = ngram

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        lowered = text.lower()
        tokens = [t for t in _WORD_SPLIT.split(lowered) if t]
        grams: list[str] = []
        if not tokens:
            tokens = [lowered]
        for i in range(len(tokens)):
            grams.append(tokens[i])
            if i + self._ngram - 1 < len(tokens):
                grams.append(" ".join(tokens[i : i + self._ngram]))
        for gram in grams:
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector


__all__ = ["HashEmbeddingService"]
