from __future__ import annotations

from typing import Any

import weaviate
from weaviate.classes.config import Configure, DataType, Property

from agent_core.config import settings
from agent_core.services.repository_projection_service import (
    REPOSITORY_CONTEXT_COLLECTION,
)


class WeaviateSchemaStore:
    PROJECT_MEMORY = "ProjectMemory"
    PLAN_NODE_CONTEXT = "PlanNodeContext"
    CONTEXT_CAPSULE = "ContextCapsule"

    def __init__(self) -> None:
        self.client = weaviate.connect_to_custom(
            http_host=settings.weaviate_http_host,
            http_port=settings.weaviate_http_port,
            http_secure=settings.weaviate_secure,
            grpc_host=settings.weaviate_grpc_host,
            grpc_port=settings.weaviate_grpc_port,
            grpc_secure=settings.weaviate_secure,
        )

    async def ensure_schema(self) -> None:
        self._ensure_project_memory()
        self._ensure_plan_node_context()
        self._ensure_context_capsule()
        self._ensure_repository_context()

    def _ensure_project_memory(self) -> None:
        if self.client.collections.exists(self.PROJECT_MEMORY):
            return
        self.client.collections.create(
            name=self.PROJECT_MEMORY,
            vector_config=Configure.Vectors.self_provided(),
            properties=[
                Property(name="project_key", data_type=DataType.TEXT),
                Property(name="memory_id", data_type=DataType.TEXT),
                Property(name="source_type", data_type=DataType.TEXT),
                Property(name="title", data_type=DataType.TEXT),
                Property(name="content", data_type=DataType.TEXT),
                Property(name="summary", data_type=DataType.TEXT),
                Property(name="tags", data_type=DataType.TEXT_ARRAY),
            ],
        )

    def _ensure_plan_node_context(self) -> None:
        if self.client.collections.exists(self.PLAN_NODE_CONTEXT):
            return
        self.client.collections.create(
            name=self.PLAN_NODE_CONTEXT,
            vector_config=Configure.Vectors.self_provided(),
            properties=[
                Property(name="project_key", data_type=DataType.TEXT),
                Property(name="plan_version_id", data_type=DataType.TEXT),
                Property(name="plan_node_id", data_type=DataType.TEXT),
                Property(name="kind", data_type=DataType.TEXT),
                Property(name="title", data_type=DataType.TEXT),
                Property(name="content", data_type=DataType.TEXT),
            ],
        )

    def _ensure_context_capsule(self) -> None:
        if self.client.collections.exists(self.CONTEXT_CAPSULE):
            return
        self.client.collections.create(
            name=self.CONTEXT_CAPSULE,
            vector_config=Configure.Vectors.self_provided(),
            properties=[
                Property(name="project_key", data_type=DataType.TEXT),
                Property(name="capsule_id", data_type=DataType.TEXT),
                Property(name="plan_node_id", data_type=DataType.TEXT),
                Property(name="capsule_type", data_type=DataType.TEXT),
                Property(name="content", data_type=DataType.TEXT),
            ],
        )

    def _ensure_repository_context(self) -> None:
        if self.client.collections.exists(REPOSITORY_CONTEXT_COLLECTION):
            return
        self.client.collections.create(
            name=REPOSITORY_CONTEXT_COLLECTION,
            vector_config=Configure.Vectors.self_provided(),
            properties=[
                Property(name="project_id", data_type=DataType.TEXT),
                Property(name="repository_key", data_type=DataType.TEXT),
                Property(name="relative_path", data_type=DataType.TEXT),
                Property(name="name", data_type=DataType.TEXT),
                Property(name="kind", data_type=DataType.TEXT),
                Property(name="language", data_type=DataType.TEXT),
                Property(name="content", data_type=DataType.TEXT),
            ],
        )

    async def upsert_text(
        self,
        *,
        collection: str,
        object_id: str,
        text: str,
        properties: dict[str, Any],
        vector: list[float] | None = None,
    ) -> None:
        target = self.client.collections.get(collection)
        payload = {**properties, "content": text}
        if target.data.exists(uuid=object_id):
            target.data.update(uuid=object_id, properties=payload, vector=vector)
        else:
            target.data.insert(properties=payload, uuid=object_id, vector=vector)

    async def search(
        self,
        *,
        collection: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        target = self.client.collections.get(collection)
        response = target.query.bm25(query=query, limit=limit)
        return [
            {
                "id": str(item.uuid),
                "properties": dict(item.properties),
                "score": getattr(getattr(item, "metadata", None), "score", None),
            }
            for item in response.objects
        ]

    def close(self) -> None:
        self.client.close()
