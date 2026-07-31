from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.code_analysis import (
    CodeRelationship,
    CodeRelationshipKind,
    CodeSymbol,
    CodeSymbolKind,
    RepositoryIndex,
)
from agent_core.models import RepositoryRelationshipRecord, RepositorySymbolRecord


class SqlAlchemyRepositoryIndexStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def replace_index(
        self,
        *,
        project_id: UUID,
        index: RepositoryIndex,
    ) -> None:
        await self.db.execute(
            delete(RepositoryRelationshipRecord).where(
                RepositoryRelationshipRecord.project_id == project_id,
                RepositoryRelationshipRecord.repository_key == index.repository_key,
            )
        )
        await self.db.execute(
            delete(RepositorySymbolRecord).where(
                RepositorySymbolRecord.project_id == project_id,
                RepositorySymbolRecord.repository_key == index.repository_key,
            )
        )

        if index.symbols:
            await self.db.execute(
                insert(RepositorySymbolRecord),
                [
                    {
                        "project_id": project_id,
                        "repository_key": symbol.repository_key,
                        "symbol_key": symbol.symbol_key,
                        "relative_path": symbol.relative_path,
                        "name": symbol.name,
                        "kind": symbol.kind.value,
                        "language": symbol.language,
                        "start_line": symbol.start_line,
                        "end_line": symbol.end_line,
                        "parent_symbol_key": symbol.parent_symbol_key,
                        "symbol_metadata": symbol.metadata,
                    }
                    for symbol in index.symbols
                ],
            )

        if index.relationships:
            await self.db.execute(
                insert(RepositoryRelationshipRecord),
                [
                    {
                        "project_id": project_id,
                        "repository_key": relationship.repository_key,
                        "source_symbol_key": relationship.source_symbol_key,
                        "target_symbol_key": relationship.target_symbol_key,
                        "target_name": relationship.target_name,
                        "relationship_type": relationship.relationship_type.value,
                        "relationship_metadata": relationship.metadata,
                    }
                    for relationship in index.relationships
                ],
            )

        await self.db.commit()

    async def list_symbols(
        self,
        *,
        project_id: UUID,
        repository_key: str,
    ) -> list[CodeSymbol]:
        result = await self.db.scalars(
            select(RepositorySymbolRecord)
            .where(
                RepositorySymbolRecord.project_id == project_id,
                RepositorySymbolRecord.repository_key == repository_key,
            )
            .order_by(
                RepositorySymbolRecord.relative_path,
                RepositorySymbolRecord.start_line,
                RepositorySymbolRecord.name,
            )
        )
        return [_symbol_from_record(record) for record in result]

    async def list_relationships(
        self,
        *,
        project_id: UUID,
        repository_key: str,
    ) -> list[CodeRelationship]:
        result = await self.db.scalars(
            select(RepositoryRelationshipRecord)
            .where(
                RepositoryRelationshipRecord.project_id == project_id,
                RepositoryRelationshipRecord.repository_key == repository_key,
            )
            .order_by(
                RepositoryRelationshipRecord.source_symbol_key,
                RepositoryRelationshipRecord.relationship_type,
                RepositoryRelationshipRecord.target_name,
            )
        )
        return [_relationship_from_record(record) for record in result]


def _symbol_from_record(record: RepositorySymbolRecord) -> CodeSymbol:
    return CodeSymbol(
        symbol_key=record.symbol_key,
        repository_key=record.repository_key,
        relative_path=record.relative_path,
        name=record.name,
        kind=CodeSymbolKind(record.kind),
        language=record.language,
        start_line=record.start_line,
        end_line=record.end_line,
        parent_symbol_key=record.parent_symbol_key,
        metadata=record.symbol_metadata or {},
    )


def _relationship_from_record(record: RepositoryRelationshipRecord) -> CodeRelationship:
    return CodeRelationship(
        repository_key=record.repository_key,
        source_symbol_key=record.source_symbol_key,
        target_symbol_key=record.target_symbol_key,
        target_name=record.target_name,
        relationship_type=CodeRelationshipKind(record.relationship_type),
        metadata=record.relationship_metadata or {},
    )
