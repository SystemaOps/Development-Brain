from __future__ import annotations

from agent_core.ports.repository import RepositoryBindingStorePort, RepositoryPort
from agent_core.ports.repository_analysis import LspLookupPort, RepositoryAnalysisPort, RepositoryIndexStorePort, SyntaxExtractionPort


class GitRepository(RepositoryPort):
    """Platform-facing Git repository interface for source inspection and diffs."""


class RepositoryBindingStore(RepositoryBindingStorePort):
    """Persists repository bindings without exposing concrete storage to agents."""


class RepositoryAnalysisGateway(RepositoryAnalysisPort):
    """Indexes repositories through configured analysis adapters."""


class SyntaxExtractionGateway(SyntaxExtractionPort):
    """Wraps Tree-sitter extraction behind a platform interface."""


class LspLookupGateway(LspLookupPort):
    """Wraps LSP definition/reference lookup behind a platform interface."""


class RepositoryIndexStore(RepositoryIndexStorePort):
    """Persists repository symbols and relationships."""


__all__ = [
    "GitRepository",
    "LspLookupGateway",
    "RepositoryAnalysisGateway",
    "RepositoryBindingStore",
    "RepositoryIndexStore",
    "SyntaxExtractionGateway",
]
