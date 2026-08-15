"""Weaviate implementation of the :class:`SemanticIndex` port.

Uses the official ``weaviate-client`` v4 API.  The class is created lazily on
first use with explicit vectors (no vectorizer), so the embedding model is
provided by the caller via :class:`~brain.ports.embeddings.EmbeddingService`.
Search filters (project/repository/revision/entity_type) are translated to
Weaviate property filters.
"""

from __future__ import annotations

import socket
import uuid
from typing import Any

from brain.adapters.weaviate.config import WeaviateSettings
from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.knowledge import SemanticRecord
from brain.ports.embeddings import EmbeddingService
from brain.ports.semantic_index import SemanticIndex

_PROPERTIES = [
    "entity_id",
    "entity_type",
    "text",
    "project_id",
    "repository_id",
    "revision",
    "source",
]


def weaviate_reachable(settings: WeaviateSettings) -> bool:
    """Best-effort reachability probe for the Weaviate HTTP endpoint."""
    try:
        with socket.create_connection((settings.host, settings.port), timeout=2):
            return True
    except OSError:
        return False


class WeaviateSemanticIndex(SemanticIndex):
    """Semantic index backed by a Weaviate collection with explicit vectors."""

    def __init__(
        self,
        *,
        embeddings: EmbeddingService,
        settings: WeaviateSettings | None = None,
    ) -> None:
        self._embeddings = embeddings
        self._settings = settings or WeaviateSettings.from_env()
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from weaviate import connect_to_custom
            from weaviate.classes.config import Configure, DataType, Property

            client = connect_to_custom(
                http_host=self._settings.host,
                http_port=self._settings.port,
                http_secure=False,
                grpc_host=self._settings.host,
                grpc_port=self._settings.grpc_port,
                grpc_secure=False,
            )
            if not client.collections.exists(self._settings.class_name):
                client.collections.create(
                    self._settings.class_name,
                    vectorizer_config=Configure.Vectorizer.none(),
                    properties=[
                        Property(name=name, data_type=DataType.TEXT) for name in _PROPERTIES
                    ],
                )
            self._client = client
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def clear(self) -> None:
        """Delete all objects from the collection (test isolation)."""
        client = self._get_client()
        collection = client.collections.get(self._settings.class_name)
        uuids = [obj.uuid for obj in collection.iterator()]
        for record_id in uuids:
            collection.data.delete_by_id(str(record_id))

    async def index(self, records: list[SemanticRecord]) -> None:
        if not records:
            return
        vectors = await self._embeddings.embed([record.text for record in records])
        client = self._get_client()
        collection = client.collections.get(self._settings.class_name)
        for record, vector in zip(records, vectors, strict=True):
            collection.data.insert(
                uuid=record.record_id,
                properties={
                    "entity_id": str(record.entity_id),
                    "entity_type": record.entity_type,
                    "text": record.text,
                    "project_id": str(record.project_id) if record.project_id else None,
                    "repository_id": str(record.repository_id) if record.repository_id else None,
                    "revision": record.revision,
                    "source": record.source,
                },
                vector=vector,
            )

    async def delete(self, ids: list[uuid.UUID]) -> None:
        client = self._get_client()
        collection = client.collections.get(self._settings.class_name)
        for record_id in ids:
            collection.data.delete_by_id(str(record_id))

    async def search(
        self, query: str, filters: dict[str, object], limit: int
    ) -> list[SemanticRecord]:
        # Lexical search: BM25-like via Weaviate's bm25 operator, or a raw
        # text query when BM25 is unavailable.  Filters are applied together.
        client = self._get_client()
        collection = client.collections.get(self._settings.class_name)
        where = _build_filter(filters)
        response = collection.query.bm25(
            query=query,
            limit=limit,
            filters=where,
        )
        return [_record_from_object(obj) for obj in response.objects]

    async def search_by_vector(
        self,
        vector: list[float],
        filters: dict[str, object],
        limit: int,
    ) -> list[SemanticRecord]:
        client = self._get_client()
        collection = client.collections.get(self._settings.class_name)
        where = _build_filter(filters)
        response = collection.query.near_vector(
            near_vector=vector,
            limit=limit,
            filters=where,
        )
        return [_record_from_object(obj) for obj in response.objects]


def _build_filter(filters: dict[str, object]) -> Any | None:
    clauses: list[Any] = []
    from weaviate.classes.query import Filter

    for prop in ("project_id", "repository_id", "revision", "entity_type"):
        value = filters.get(prop)
        if value is None:
            continue
        clauses.append(Filter.by_property(prop).equal(str(value)))
    if not clauses:
        return None
    combined = clauses[0]
    for clause in clauses[1:]:
        combined = combined & clause
    return combined


def _record_from_object(obj: Any) -> SemanticRecord:
    props = obj.properties
    project = _uuid_or_none(props.get("project_id"))
    repository = _uuid_or_none(props.get("repository_id"))
    return SemanticRecord(
        record_id=uuid.UUID(str(obj.uuid)),
        entity_id=uuid.UUID(str(props.get("entity_id"))),
        entity_type=str(props.get("entity_type", "")),
        text=str(props.get("text", "")),
        project_id=ProjectId(project) if project is not None else None,
        repository_id=RepositoryId(repository) if repository is not None else None,
        revision=props.get("revision"),
        source=props.get("source"),
    )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


__all__ = ["WeaviateSemanticIndex", "WeaviateSettings", "weaviate_reachable"]
