"""Knowledge graph repository port.

Relationship-heavy engineering knowledge (code graph, topology, test links,
task-code links) is stored behind this protocol.  Neo4j is one implementation;
the domain never depends on a graph provider directly.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from brain.domain.identity import ProjectId
from brain.domain.knowledge import KnowledgeEvidence


class GraphEntity(BaseModel):
    id: uuid.UUID
    label: str
    project_id: ProjectId | None = None
    properties: dict[str, object] = Field(default_factory=dict)
    provenance: list[KnowledgeEvidence] = Field(default_factory=list)


class GraphRelation(BaseModel):
    subject_id: uuid.UUID
    relation_type: str
    object_id: uuid.UUID
    properties: dict[str, object] = Field(default_factory=dict)
    provenance: list[KnowledgeEvidence] = Field(default_factory=list)


@runtime_checkable
class KnowledgeGraphRepository(Protocol):
    async def upsert_entities(self, entities: list[GraphEntity]) -> None: ...

    async def upsert_relations(self, relations: list[GraphRelation]) -> None: ...

    async def traverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[str],
        depth: int,
    ) -> list[GraphEntity]: ...
