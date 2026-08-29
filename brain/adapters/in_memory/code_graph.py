"""In-memory reference implementation of the code graph repository.

Reference adapter for the ``CodeGraphRepository`` port so the code
intelligence service and contract tests run without PostgreSQL.
"""

from __future__ import annotations

from brain.domain.code_intelligence import (
    CodeRelation,
    ParsedFile,
    Symbol,
)
from brain.domain.identity import RepositoryId


class InMemoryCodeGraphRepository:
    """In-memory symbols/relations indexed by repository + revision."""

    def __init__(self) -> None:
        self._symbols: dict[tuple[str, str, str], Symbol] = {}
        self._relations: dict[tuple[str, str, str], CodeRelation] = {}
        self._files: dict[tuple[str, str, str], ParsedFile] = {}

    async def save_symbols(self, symbols: list[Symbol]) -> list[Symbol]:
        for symbol in symbols:
            key = (
                str(symbol.identity.repository_id),
                symbol.identity.revision,
                symbol.identity_key,
            )
            self._symbols[key] = symbol
        return symbols

    async def save_relations(self, relations: list[CodeRelation]) -> list[CodeRelation]:
        for relation in relations:
            self._relations[
                (
                    str(relation.repository_id),
                    relation.revision,
                    relation.id.__str__(),
                )
            ] = relation
        return relations

    async def save_parsed_file(self, parsed: ParsedFile) -> ParsedFile:
        await self.save_symbols(parsed.symbols)
        await self.save_relations(parsed.relations)
        self._files[(str(parsed.repository_id), parsed.revision, parsed.path)] = parsed
        return parsed

    async def get_symbol(
        self, repository_id: RepositoryId, revision: str, identity_key: str
    ) -> Symbol | None:
        return self._symbols.get((str(repository_id), revision, identity_key))

    async def list_symbols(self, repository_id: RepositoryId, revision: str) -> list[Symbol]:
        return [
            symbol
            for (repo, rev, _key), symbol in self._symbols.items()
            if repo == str(repository_id) and rev == revision
        ]

    async def list_relations(
        self, repository_id: RepositoryId, revision: str
    ) -> list[CodeRelation]:
        return [
            relation
            for (repo, rev, _key), relation in self._relations.items()
            if repo == str(repository_id) and rev == revision
        ]

    async def find_symbol(
        self, repository_id: RepositoryId, revision: str, qualified_name: str
    ) -> list[Symbol]:
        return [
            symbol
            for symbol in await self.list_symbols(repository_id, revision)
            if symbol.qualified_name == qualified_name
        ]

    async def expire_revision(self, repository_id: RepositoryId, revision: str) -> None:
        prefix = (str(repository_id), revision)
        for key in list(self._symbols):
            if key[:2] == prefix:
                del self._symbols[key]
        for key in list(self._relations):
            if key[:2] == prefix:
                del self._relations[key]
        for key in list(self._files):
            if key[:2] == prefix:
                del self._files[key]
