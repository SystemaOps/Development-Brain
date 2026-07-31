from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.adapters.lsp import LegacyPythonLspLookup
from agent_core.adapters.repository_analysis import PythonAstRepositoryAnalyzer
from agent_core.adapters.repository_filesystem import LocalRepositoryFilesystem
from agent_core.adapters.tree_sitter_analysis import TreeSitterPythonExtractor
from agent_core.config import settings
from agent_core.domain.code_analysis import CodeRelationship, CodeSymbol
from agent_core.domain.repositories import RepositoryBinding, RepositoryPathError
from agent_core.models import Project
from agent_core.persistence.repository_bindings import SqlAlchemyRepositoryBindingStore
from agent_core.persistence.repository_index import SqlAlchemyRepositoryIndexStore
from agent_core.ports.graph_store import GraphStorePort
from agent_core.ports.repository import RepositorySnapshot
from agent_core.ports.vector_store import VectorStorePort
from agent_core.services.repository_projection_service import (
    RepositoryNeo4jProjector,
    RepositoryVectorProjector,
)


class RepositoryIndexSummary(BaseModel):
    project_id: UUID
    project_key: str
    repository_key: str
    symbol_count: int
    relationship_count: int
    warnings: list[str]
    graph_mutations: int = 0
    vector_upserts: int = 0


class RepositoryAnalysisService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        repository_mount_root: str | None = None,
        graph_store: GraphStorePort | None = None,
        vector_store: VectorStorePort | None = None,
    ):
        self.db = db
        self.repository_mount_root = repository_mount_root or settings.repository_mount_root
        self.binding_store = SqlAlchemyRepositoryBindingStore(db)
        self.index_store = SqlAlchemyRepositoryIndexStore(db)
        self.graph_store = graph_store
        self.vector_store = vector_store

    async def bind_repository(
        self,
        *,
        project_key: str,
        binding: RepositoryBinding,
    ) -> RepositoryBinding:
        project = await self._get_project(project_key)
        self._validate_mount_root(binding)
        return await self.binding_store.upsert_binding(
            project_id=project.id,
            binding=binding,
        )

    async def get_binding(
        self,
        *,
        project_key: str,
        repository_key: str,
    ) -> RepositoryBinding:
        project = await self._get_project(project_key)
        binding = await self.binding_store.get_binding(
            project_id=project.id,
            repository_key=repository_key,
        )
        if binding is None:
            raise KeyError(repository_key)
        return binding

    async def index_repository(
        self,
        *,
        project_key: str,
        repository_key: str,
        project_to_graph: bool = False,
        upsert_to_vector: bool = False,
    ) -> RepositoryIndexSummary:
        project = await self._get_project(project_key)
        binding = await self._get_binding(project.id, repository_key)

        lsp_lookup = LegacyPythonLspLookup(binding=binding)
        analyzer = PythonAstRepositoryAnalyzer(
            [binding],
            syntax_extractor=TreeSitterPythonExtractor(),
            lsp_lookup=lsp_lookup,
        )
        index = await analyzer.index_repository(repository_key=repository_key)
        await self.index_store.replace_index(project_id=project.id, index=index)

        graph_mutations = 0
        if project_to_graph:
            created_graph_store = self.graph_store is None
            graph_store = self.graph_store or _build_neo4j_store()
            graph_mutations = await RepositoryNeo4jProjector(graph_store).project_index(
                project_id=project.id,
                index=index,
            )
            if created_graph_store:
                await _close_if_possible(graph_store)

        vector_upserts = 0
        if upsert_to_vector:
            created_vector_store = self.vector_store is None
            vector_store = self.vector_store or _build_weaviate_store()
            vector_upserts = await RepositoryVectorProjector(
                vector_store
            ).upsert_repository_context(project_id=project.id, index=index)
            if created_vector_store:
                await _close_if_possible(vector_store)

        return RepositoryIndexSummary(
            project_id=project.id,
            project_key=project.project_key,
            repository_key=repository_key,
            symbol_count=len(index.symbols),
            relationship_count=len(index.relationships),
            warnings=list(index.warnings),
            graph_mutations=graph_mutations,
            vector_upserts=vector_upserts,
        )

    async def snapshot(
        self,
        *,
        project_key: str,
        repository_key: str,
    ) -> RepositorySnapshot:
        project = await self._get_project(project_key)
        binding = await self._get_binding(project.id, repository_key)
        return await LocalRepositoryFilesystem([binding]).snapshot(
            repository_key=repository_key,
        )

    async def list_symbols(
        self,
        *,
        project_key: str,
        repository_key: str,
    ) -> list[CodeSymbol]:
        project = await self._get_project(project_key)
        return await self.index_store.list_symbols(
            project_id=project.id,
            repository_key=repository_key,
        )

    async def list_relationships(
        self,
        *,
        project_key: str,
        repository_key: str,
    ) -> list[CodeRelationship]:
        project = await self._get_project(project_key)
        return await self.index_store.list_relationships(
            project_id=project.id,
            repository_key=repository_key,
        )

    async def search_repository_context(
        self,
        *,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        vector_store = self.vector_store or _build_weaviate_store()
        try:
            return await RepositoryVectorProjector(vector_store).search_repository_context(
                query=query,
                limit=limit,
            )
        finally:
            await _close_if_possible(vector_store)

    async def _get_project(self, project_key: str) -> Project:
        project = await self.db.scalar(select(Project).where(Project.project_key == project_key))
        if project is None:
            raise KeyError(project_key)
        return project

    async def _get_binding(
        self,
        project_id: UUID,
        repository_key: str,
    ) -> RepositoryBinding:
        binding = await self.binding_store.get_binding(
            project_id=project_id,
            repository_key=repository_key,
        )
        if binding is None:
            raise KeyError(repository_key)
        return binding

    def _validate_mount_root(self, binding: RepositoryBinding) -> None:
        mount_root = Path(self.repository_mount_root).expanduser().resolve(strict=False)
        try:
            mount_path = Path(binding.mount_path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise RepositoryPathError(
                f"Repository mount does not exist: {binding.mount_path}"
            ) from exc

        try:
            mount_path.relative_to(mount_root)
        except ValueError as exc:
            raise RepositoryPathError(
                f"Repository mount must be under configured root: {mount_root}"
            ) from exc


def _build_neo4j_store() -> GraphStorePort:
    from agent_core.adapters.neo4j_store import Neo4jProjectionStore

    return Neo4jProjectionStore()


def _build_weaviate_store() -> VectorStorePort:
    from agent_core.adapters.weaviate_store import WeaviateSchemaStore

    return WeaviateSchemaStore()


async def _close_if_possible(store: object) -> None:
    close = getattr(store, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result
