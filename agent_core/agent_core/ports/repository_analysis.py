from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from agent_core.domain.code_analysis import (
    CodeRelationship,
    CodeSymbol,
    LspLookupResult,
    RepositoryIndex,
    SyntaxExtractionResult,
)


class RepositoryAnalysisPort(Protocol):
    async def index_repository(self, *, repository_key: str) -> RepositoryIndex:
        ...


class SyntaxExtractionPort(Protocol):
    def extract_python_file(
        self,
        *,
        repository_key: str,
        relative_path: str,
        absolute_path: Path,
    ) -> SyntaxExtractionResult:
        ...


class LspLookupPort(Protocol):
    def is_available(self) -> bool:
        ...

    async def definition(
        self,
        *,
        repository_key: str,
        relative_path: str,
        line: int,
        character: int,
    ) -> LspLookupResult:
        ...

    async def references(
        self,
        *,
        repository_key: str,
        relative_path: str,
        line: int,
        character: int,
    ) -> LspLookupResult:
        ...


class RepositoryIndexStorePort(Protocol):
    async def replace_index(
        self,
        *,
        project_id: UUID,
        index: RepositoryIndex,
    ) -> None:
        ...

    async def list_symbols(
        self,
        *,
        project_id: UUID,
        repository_key: str,
    ) -> list[CodeSymbol]:
        ...

    async def list_relationships(
        self,
        *,
        project_id: UUID,
        repository_key: str,
    ) -> list[CodeRelationship]:
        ...
