"""Code intelligence ports (Phase 7).

``LanguageParser`` is the pluggable parsing contract (Python AST first, more
languages later).  ``CodeGraphRepository`` persists parsed symbols and
relations at a revision so the impact-analysis service can answer
``where/what calls/what calls it`` queries for an exact repository revision.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.code_intelligence import (
    CodeRelation,
    ParsedFile,
    Symbol,
    SymbolIdentity,
)
from brain.domain.identity import RepositoryId


@runtime_checkable
class LanguageParser(Protocol):
    """Parses source content into a :class:`ParsedFile`.

    Implementations are language-specific (Python AST, ...) and must be pure:
    same input at the same revision yields the same symbols and relations.
    """

    async def parse(
        self,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        content: str,
    ) -> ParsedFile | None: ...


@runtime_checkable
class CodeGraphRepository(Protocol):
    """Durable storage for parsed symbols and relations at a revision.

    Writing replaces the previous facts for the given repository+revision
    (incremental update re-uses the same repository but a newer revision);
    queries always filter by repository and revision so results are exact.
    """

    async def save_symbols(self, symbols: list[Symbol]) -> list[Symbol]: ...

    async def save_relations(self, relations: list[CodeRelation]) -> list[CodeRelation]: ...

    async def save_parsed_file(self, parsed: ParsedFile) -> ParsedFile: ...

    async def get_symbol(
        self, repository_id: RepositoryId, revision: str, identity_key: str
    ) -> Symbol | None: ...

    async def list_symbols(self, repository_id: RepositoryId, revision: str) -> list[Symbol]: ...

    async def list_relations(
        self, repository_id: RepositoryId, revision: str
    ) -> list[CodeRelation]: ...

    async def find_symbol(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[Symbol]: ...

    async def expire_revision(self, repository_id: RepositoryId, revision: str) -> None: ...


@runtime_checkable
class CodeIntelligencePort(Protocol):
    """High-level code intelligence operations over the parsed graph.

    Implementations combine a ``LanguageParser`` with a ``CodeGraphRepository``
    and expose impact-analysis style queries.
    """

    async def build_revision(self, repository_id: RepositoryId, revision: str) -> int: ...

    async def where_defined(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[Symbol]: ...

    async def what_calls(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[CodeRelation]: ...

    async def what_is_called_by(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[CodeRelation]: ...


__all__ = [
    "CodeGraphRepository",
    "CodeIntelligencePort",
    "LanguageParser",
    "SymbolIdentity",
]
