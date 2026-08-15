"""Embedding service adapters (Task 9.3).

Deterministic local embeddings today; remote models can be added behind the
same port later.
"""

from brain.adapters.embeddings.hash_embedding import HashEmbeddingService

__all__ = ["HashEmbeddingService"]
