"""Weaviate semantic index adapter (Phase 9).

Implements the :class:`~brain.ports.semantic_index.SemanticIndex` port against
a Weaviate collection using explicit vectors produced by an
:class:`~brain.ports.embeddings.EmbeddingService`.
"""

from brain.adapters.weaviate.config import WeaviateSettings
from brain.adapters.weaviate.semantic_index import WeaviateSemanticIndex, weaviate_reachable

__all__ = ["WeaviateSemanticIndex", "WeaviateSettings", "weaviate_reachable"]
