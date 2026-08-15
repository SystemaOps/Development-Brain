"""In-memory knowledge graph reference implementation.

A simple directed multi-graph keyed by entity id.  Traversal performs a
breadth-first search over the allowed relation types.
"""

from __future__ import annotations

import threading
import uuid

from brain.ports.knowledge_graph import GraphEntity, GraphRelation


class InMemoryKnowledgeGraph:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entities: dict[uuid.UUID, GraphEntity] = {}
        self._relations_out: dict[uuid.UUID, list[GraphRelation]] = {}

    async def upsert_entities(self, entities: list[GraphEntity]) -> None:
        with self._lock:
            for entity in entities:
                self._entities[entity.id] = entity

    async def upsert_relations(self, relations: list[GraphRelation]) -> None:
        with self._lock:
            for relation in relations:
                self._relations_out.setdefault(relation.subject_id, []).append(relation)

    async def traverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[str],
        depth: int,
    ) -> list[GraphEntity]:
        reached: set[uuid.UUID] = set()
        frontier = list(start_ids)
        for _ in range(depth):
            if not frontier:
                break
            reached.update(frontier)
            next_frontier: list[uuid.UUID] = []
            with self._lock:
                for subject_id in frontier:
                    for relation in self._relations_out.get(subject_id, []):
                        if (
                            relation.relation_type in relation_types
                            and relation.object_id not in reached
                        ):
                            next_frontier.append(relation.object_id)
            frontier = next_frontier
        reached.update(frontier)
        with self._lock:
            return [self._entities[i] for i in reached if i in self._entities]
