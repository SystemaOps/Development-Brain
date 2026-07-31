from __future__ import annotations

from uuid import UUID, uuid5, NAMESPACE_URL

from agent_core.domain.code_analysis import (
    CodeRelationship,
    CodeSymbol,
    RepositoryIndex,
)
from agent_core.ports.graph_store import GraphStorePort
from agent_core.ports.vector_store import VectorStorePort


REPOSITORY_CONTEXT_COLLECTION = "RepositoryCodeContext"


class RepositoryNeo4jProjector:
    def __init__(self, graph_store: GraphStorePort):
        self.graph_store = graph_store

    async def project_index(self, *, project_id: UUID, index: RepositoryIndex) -> int:
        await self.graph_store.ensure_schema()
        repository_node_key = _repository_node_key(project_id, index.repository_key)
        await self.graph_store.upsert_node(
            labels=("Repository",),
            key=repository_node_key,
            properties={
                "key": repository_node_key,
                "project_id": str(project_id),
                "repository_key": index.repository_key,
            },
        )

        mutation_count = 1
        for symbol in index.symbols:
            await self.graph_store.upsert_node(
                labels=("CodeSymbol", _symbol_label(symbol)),
                key=symbol.symbol_key,
                properties=_symbol_properties(project_id, symbol),
            )
            await self.graph_store.upsert_relation(
                from_key=repository_node_key,
                to_key=symbol.symbol_key,
                relation_type="CONTAINS_SYMBOL",
                properties={"repository_key": index.repository_key},
            )
            mutation_count += 2

        for relationship in index.relationships:
            mutation_count += await self._project_relationship(relationship)

        return mutation_count

    async def _project_relationship(self, relationship: CodeRelationship) -> int:
        target_key = relationship.target_symbol_key
        mutation_count = 0
        if target_key is None:
            target_key = (
                f"{relationship.repository_key}:unresolved:"
                f"{relationship.relationship_type.value}:{relationship.target_name}"
            )
            await self.graph_store.upsert_node(
                labels=("UnresolvedCodeReference",),
                key=target_key,
                properties={
                    "key": target_key,
                    "repository_key": relationship.repository_key,
                    "target_name": relationship.target_name,
                },
            )
            mutation_count += 1

        await self.graph_store.upsert_relation(
            from_key=relationship.source_symbol_key,
            to_key=target_key,
            relation_type=relationship.relationship_type.value.upper(),
            properties={
                "repository_key": relationship.repository_key,
                "target_name": relationship.target_name,
                **relationship.metadata,
            },
        )
        return mutation_count + 1


class RepositoryVectorProjector:
    def __init__(self, vector_store: VectorStorePort):
        self.vector_store = vector_store

    async def upsert_repository_context(
        self,
        *,
        project_id: UUID,
        index: RepositoryIndex,
    ) -> int:
        await self.vector_store.ensure_schema()
        count = 0
        for symbol in index.symbols:
            await self.vector_store.upsert_text(
                collection=REPOSITORY_CONTEXT_COLLECTION,
                object_id=_stable_vector_id(symbol.symbol_key),
                text=_symbol_text(symbol),
                properties=_symbol_properties(project_id, symbol),
            )
            count += 1
        return count

    async def search_repository_context(
        self,
        *,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        return await self.vector_store.search(
            collection=REPOSITORY_CONTEXT_COLLECTION,
            query=query,
            limit=limit,
        )


def _repository_node_key(project_id: UUID, repository_key: str) -> str:
    return f"project:{project_id}:repository:{repository_key}"


def _symbol_label(symbol: CodeSymbol) -> str:
    return {
        "file": "CodeFile",
        "class": "CodeClass",
        "function": "CodeFunction",
        "import": "CodeImport",
    }[symbol.kind.value]


def _symbol_properties(project_id: UUID, symbol: CodeSymbol) -> dict:
    return {
        "key": symbol.symbol_key,
        "project_id": str(project_id),
        "repository_key": symbol.repository_key,
        "relative_path": symbol.relative_path,
        "name": symbol.name,
        "kind": symbol.kind.value,
        "language": symbol.language,
        "start_line": symbol.start_line,
        "end_line": symbol.end_line,
        "parent_symbol_key": symbol.parent_symbol_key,
        **symbol.metadata,
    }


def _symbol_text(symbol: CodeSymbol) -> str:
    parts = [
        f"{symbol.kind.value}: {symbol.name}",
        f"path: {symbol.relative_path}",
        f"language: {symbol.language}",
    ]
    qualname = symbol.metadata.get("qualname")
    if qualname:
        parts.append(f"qualified name: {qualname}")
    if symbol.start_line is not None:
        parts.append(f"line: {symbol.start_line}")
    return "\n".join(parts)


def _stable_vector_id(source_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ada:repository-context:{source_id}"))
