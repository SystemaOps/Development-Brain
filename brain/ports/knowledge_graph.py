"""Knowledge graph repository port.

Relationship-heavy engineering knowledge (code graph, topology, test links,
task-code links) is stored behind this protocol.  Neo4j is one implementation;
the domain never depends on a graph provider directly.

Every node/relation carries optional revision awareness (``repository_id``,
``commit_sha``) plus provenance (``origin`` / ``confidence``) so code facts stay
exact per repository revision and LLM-inferred edges are never presented as
deterministic truth (Tasks 8.2, 8.3).
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.knowledge import KnowledgeEvidence


class GraphEntity(BaseModel):
    """A node in the knowledge graph."""

    id: uuid.UUID
    label: GraphLabel
    project_id: ProjectId | None = None
    properties: dict[str, object] = Field(default_factory=dict)
    repository_id: RepositoryId | None = None
    revision: str | None = None
    provenance: list[KnowledgeEvidence] = Field(default_factory=list)


class GraphRelation(BaseModel):
    """A typed, revision-aware edge between two graph nodes."""

    subject_id: uuid.UUID
    relation_type: RelationType
    object_id: uuid.UUID
    properties: dict[str, object] = Field(default_factory=dict)
    repository_id: RepositoryId | None = None
    revision: str | None = None
    provenance: list[KnowledgeEvidence] = Field(default_factory=list)


@runtime_checkable
class KnowledgeGraphRepository(Protocol):
    """Graph storage with traversal, reverse traversal, and revision filters."""

    async def upsert_entities(self, entities: list[GraphEntity]) -> None: ...

    async def upsert_relations(self, relations: list[GraphRelation]) -> None: ...

    async def traverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType],
        depth: int,
        *,
        revision: str | None = None,
    ) -> list[GraphEntity]: ...

    async def traverse_reverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType],
        depth: int,
        *,
        revision: str | None = None,
    ) -> list[GraphEntity]: ...

    async def neighborhood(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType] | None = None,
        *,
        direction: str = "both",
        revision: str | None = None,
    ) -> list[GraphEntity]: ...

    async def find_entities(
        self,
        label: GraphLabel | None = None,
        *,
        project_id: ProjectId | None = None,
        revision: str | None = None,
    ) -> list[GraphEntity]: ...

    async def find_relations(
        self,
        relation_type: RelationType | None = None,
        *,
        subject_id: uuid.UUID | None = None,
        object_id: uuid.UUID | None = None,
        revision: str | None = None,
    ) -> list[GraphRelation]: ...


__all__ = ["GraphEntity", "GraphRelation", "KnowledgeGraphRepository"]
