"""In-memory knowledge graph reference implementation.

A simple directed multi-graph keyed by entity id.  Traversal performs a
breadth-first search over the allowed relation types; reverse traversal walks
edges backwards; both honor an optional revision filter.  This is the
reference behavior the Neo4j adapter must match.
"""

from __future__ import annotations

import threading
import uuid

from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.identity import ProjectId
from brain.ports.knowledge_graph import GraphEntity, GraphRelation


class InMemoryKnowledgeGraph:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entities: dict[uuid.UUID, GraphEntity] = {}
        self._relations_out: dict[uuid.UUID, list[GraphRelation]] = {}
        self._relations_in: dict[uuid.UUID, list[GraphRelation]] = {}

    async def upsert_entities(self, entities: list[GraphEntity]) -> None:
        with self._lock:
            for entity in entities:
                self._entities[entity.id] = entity

    async def upsert_relations(self, relations: list[GraphRelation]) -> None:
        with self._lock:
            for relation in relations:
                self._relations_out.setdefault(relation.subject_id, []).append(relation)
                self._relations_in.setdefault(relation.object_id, []).append(relation)

    async def traverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType],
        depth: int,
        *,
        revision: str | None = None,
    ) -> list[GraphEntity]:
        return self._bfs(start_ids, relation_types, depth, direction="forward", revision=revision)

    async def traverse_reverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType],
        depth: int,
        *,
        revision: str | None = None,
    ) -> list[GraphEntity]:
        return self._bfs(start_ids, relation_types, depth, direction="reverse", revision=revision)

    async def neighborhood(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType] | None = None,
        *,
        direction: str = "both",
        revision: str | None = None,
    ) -> list[GraphEntity]:
        types = list(relation_types) if relation_types is not None else None
        return self._bfs(start_ids, types, 1, direction=direction, revision=revision)

    async def find_entities(
        self,
        label: GraphLabel | None = None,
        *,
        project_id: ProjectId | None = None,
        revision: str | None = None,
    ) -> list[GraphEntity]:
        with self._lock:
            result = []
            for entity in self._entities.values():
                if label is not None and entity.label != label:
                    continue
                if project_id is not None and entity.project_id != project_id:
                    continue
                if revision is not None and entity.revision != revision:
                    continue
                result.append(entity)
            return result

    async def find_relations(
        self,
        relation_type: RelationType | None = None,
        *,
        subject_id: uuid.UUID | None = None,
        object_id: uuid.UUID | None = None,
        revision: str | None = None,
    ) -> list[GraphRelation]:
        with self._lock:
            result = []
            seen: set[tuple[uuid.UUID, str, uuid.UUID]] = set()
            for relations in self._relations_out.values():
                for relation in relations:
                    if relation_type is not None and relation.relation_type != relation_type:
                        continue
                    if subject_id is not None and relation.subject_id != subject_id:
                        continue
                    if object_id is not None and relation.object_id != object_id:
                        continue
                    if revision is not None and relation.revision != revision:
                        continue
                    key = (relation.subject_id, relation.relation_type.value, relation.object_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append(relation)
            return result

    def _bfs(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType] | None,
        depth: int,
        *,
        direction: str,
        revision: str | None,
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
                    out_relations = self._relations_out.get(subject_id, [])
                    in_relations = self._relations_in.get(subject_id, [])
                    if direction == "reverse":
                        edges = [("in", r) for r in in_relations]
                    elif direction == "forward":
                        edges = [("out", r) for r in out_relations]
                    else:
                        edges = [("out", r) for r in out_relations] + [
                            ("in", r) for r in in_relations
                        ]
                    for edge_dir, relation in edges:
                        if (
                            relation_types is not None
                            and relation.relation_type not in relation_types
                        ):
                            continue
                        if revision is not None and relation.revision != revision:
                            continue
                        neighbor = relation.subject_id if edge_dir == "in" else relation.object_id
                        if neighbor not in reached:
                            next_frontier.append(neighbor)
            frontier = next_frontier
        reached.update(frontier)
        with self._lock:
            return [self._entities[i] for i in reached if i in self._entities]
