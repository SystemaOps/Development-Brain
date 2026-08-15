"""Neo4j implementation of the :class:`KnowledgeGraphRepository` port.

Nodes are stored with the canonical :class:`~brain.domain.graph_schema.GraphLabel`
as the node label; edges use the controlled :class:`RelationType` vocabulary.
Every entity/relation is upserted by its ``id`` so re-projecting a revision is
idempotent, and revision-aware edges carry ``revision``/``origin``/``confidence``
as properties so queries can filter per exact revision (Task 8.4).
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from brain.adapters.neo4j.config import Neo4jSettings
from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.knowledge import KnowledgeEvidence
from brain.ports.knowledge_graph import GraphEntity, GraphRelation

if TYPE_CHECKING:
    from neo4j import AsyncDriver

_RESERVED = frozenset(
    {"id", "revision", "repository_id", "project_id", "origin", "confidence", "_label"}
)


def neo4j_reachable(uri: str) -> bool:
    """Best-effort reachability probe for the host:port of ``uri``."""
    parsed = urlparse(uri.replace("bolt+s", "bolt").replace("bolt+ssc", "bolt"))
    host = parsed.hostname or "localhost"
    port = parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


class Neo4jKnowledgeGraph:
    """Knowledge graph backed by a Neo4j database."""

    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self._settings = settings or Neo4jSettings.from_env()
        self._driver: AsyncDriver | None = None

    def _get_driver(self) -> AsyncDriver:
        if self._driver is None:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                self._settings.uri,
                auth=(self._settings.user, self._settings.password),
            )
        return self._driver

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def clear(self) -> None:
        """Delete all nodes/relations (used by tests for isolation)."""
        driver = self._get_driver()
        async with driver.session(database=self._settings.database) as session:
            await session.run("MATCH (n) DETACH DELETE n")

    async def upsert_entities(self, entities: list[GraphEntity]) -> None:
        if not entities:
            return
        driver = self._get_driver()
        async with driver.session(database=self._settings.database) as session:
            for entity in entities:
                query = (
                    f"MERGE (n:{entity.label.value} {{id: $id}}) "
                    "SET n += $props, n.revision = $revision, "
                    "n.repository_id = $repository_id, n.project_id = $project_id, "
                    "n.origin = $origin, n.confidence = $confidence"
                )
                await session.run(
                    query,
                    id=str(entity.id),
                    props=_properties(entity),
                    revision=entity.revision,
                    repository_id=_str_or_none(entity.repository_id),
                    project_id=_str_or_none(entity.project_id),
                    origin=_primary_origin(entity.provenance),
                    confidence=_primary_confidence(entity.provenance),
                )

    async def upsert_relations(self, relations: list[GraphRelation]) -> None:
        if not relations:
            return
        driver = self._get_driver()
        async with driver.session(database=self._settings.database) as session:
            for relation in relations:
                query = (
                    "MATCH (a {id: $subject}) MATCH (b {id: $object}) "
                    f"MERGE (a)-[r:{relation.relation_type.value} "
                    "{revision: coalesce($revision, ''), "
                    "subject_id: $subject, object_id: $object}]->(b) "
                    "SET r.repository_id = $repository_id, "
                    "r.origin = $origin, r.confidence = $confidence, r += $props"
                )
                await session.run(
                    query,
                    subject=str(relation.subject_id),
                    object=str(relation.object_id),
                    revision=relation.revision,
                    repository_id=_str_or_none(relation.repository_id),
                    origin=_primary_origin(relation.provenance),
                    confidence=_primary_confidence(relation.provenance),
                    props=_properties(relation),
                )

    async def traverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType],
        depth: int,
        *,
        revision: str | None = None,
    ) -> list[GraphEntity]:
        return await self._traverse(start_ids, relation_types, depth, "forward", revision)

    async def traverse_reverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType],
        depth: int,
        *,
        revision: str | None = None,
    ) -> list[GraphEntity]:
        return await self._traverse(start_ids, relation_types, depth, "reverse", revision)

    async def neighborhood(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType] | None = None,
        *,
        direction: str = "both",
        revision: str | None = None,
    ) -> list[GraphEntity]:
        return await self._traverse(start_ids, relation_types, 1, direction, revision)

    async def find_entities(
        self,
        label: GraphLabel | None = None,
        *,
        project_id: ProjectId | None = None,
        revision: str | None = None,
    ) -> list[GraphEntity]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        if label is not None:
            clauses.append("n._label = $label")
            params["label"] = label.value
        if project_id is not None:
            clauses.append("n.project_id = $project_id")
            params["project_id"] = str(project_id)
        if revision is not None:
            clauses.append("n.revision = $revision")
            params["revision"] = revision
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"MATCH (n) {where} RETURN n"
        records = await self._run_read(query, params)
        return [_entity_from_record(record["n"]) for record in records]

    async def find_relations(
        self,
        relation_type: RelationType | None = None,
        *,
        subject_id: uuid.UUID | None = None,
        object_id: uuid.UUID | None = None,
        revision: str | None = None,
    ) -> list[GraphRelation]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        if relation_type is not None:
            clauses.append("type(r) = $rtype")
            params["rtype"] = relation_type.value
        if subject_id is not None:
            clauses.append("r.subject_id = $subject")
            params["subject"] = str(subject_id)
        if object_id is not None:
            clauses.append("r.object_id = $object")
            params["object"] = str(object_id)
        if revision is not None:
            clauses.append("r.revision = $revision")
            params["revision"] = revision
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = (
            f"MATCH (a)-[r]->(b) {where} RETURN a, r, b, properties(r) AS rprops, type(r) AS rtype"
        )
        records = await self._run_read(query, params)
        return [
            _relation_from_record(record, record.get("rprops"), record.get("rtype"))
            for record in records
        ]

    async def _traverse(
        self,
        start_ids: list[uuid.UUID],
        relation_types: list[RelationType] | None,
        depth: int,
        direction: str,
        revision: str | None,
    ) -> list[GraphEntity]:
        if not start_ids:
            return []
        params: dict[str, object] = {"starts": [str(s) for s in start_ids]}
        types_pred = _types_predicate("r", relation_types)
        rev_pred = _rev_predicate("relationships(p)", revision)
        if direction == "reverse":
            pattern = f"(start)<-[r*1..{depth}]-"
        elif direction == "forward":
            pattern = f"(start)-[r*1..{depth}]->"
        else:
            pattern = f"(start)-[r*1..{depth}]-"
        # Union the start nodes with everything reachable through the allowed
        # relation types so a traversal always includes its seeds.
        query = (
            f"MATCH (start) WHERE start.id IN $starts RETURN DISTINCT start AS m "
            f"UNION "
            f"MATCH (start) WHERE start.id IN $starts "
            f"MATCH p={pattern}(m) "
            f"WHERE ALL(r IN relationships(p) WHERE {types_pred}) "
            f"{rev_pred} "
            f"RETURN DISTINCT m"
        )
        records = await self._run_read(query, params)
        return [_entity_from_record(record["m"]) for record in records]

    async def _run_read(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        driver = self._get_driver()
        async with driver.session(database=self._settings.database) as session:
            result = await session.run(query, **params)
            data = await result.data()
            return [dict(record) for record in data]


def _properties(model: GraphEntity | GraphRelation) -> dict[str, object]:
    props = dict(model.properties)
    label = model.label.value if isinstance(model, GraphEntity) else model.relation_type.value
    props.setdefault("_label", label)
    return props


def _primary_origin(provenance: Sequence[KnowledgeEvidence]) -> str | None:
    for evidence in provenance:
        return evidence.origin.value if hasattr(evidence.origin, "value") else str(evidence.origin)
    return None


def _primary_confidence(provenance: Sequence[KnowledgeEvidence]) -> float | None:
    for evidence in provenance:
        confidence = evidence.confidence
        score = confidence.score() if hasattr(confidence, "score") else float(confidence)
        return score
    return None


def _entity_from_record(node: Any) -> GraphEntity:
    props = {key: node[key] for key in node}
    label = _label_from_record(node, props)
    return GraphEntity(
        id=uuid.UUID(str(props.get("id"))),
        label=GraphLabel(label),
        project_id=_maybe_project(props.get("project_id")),
        properties={k: v for k, v in props.items() if k not in _RESERVED},
        repository_id=_maybe_repository(props.get("repository_id")),
        revision=_str_or_none(props.get("revision")),
    )


def _relation_from_record(record: dict[str, Any], rprops: Any, rtype: Any) -> GraphRelation:
    a = _as_dict(record.get("a"))
    b = _as_dict(record.get("b"))
    props = _as_dict(rprops)
    rtype_str = str(rtype or props.get("_label") or props.get("type") or "")
    return GraphRelation(
        subject_id=uuid.UUID(str(props.get("subject_id") or a.get("id"))),
        relation_type=RelationType(rtype_str),
        object_id=uuid.UUID(str(props.get("object_id") or b.get("id"))),
        properties={k: v for k, v in props.items() if k not in _RESERVED},
        repository_id=_maybe_repository(props.get("repository_id")),
        revision=_str_or_none(props.get("revision")),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {key: value[key] for key in value}


def _label_from_record(node: Any, props: dict[str, Any]) -> str:
    stored = props.get("_label")
    if stored:
        return str(stored)
    labels = getattr(node, "labels", None)
    if labels:
        for label in labels:
            return str(label)
    for key in props:
        if not key.startswith("_"):
            return str(key)
    return ""


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


def _maybe_repository(value: object) -> RepositoryId | None:
    parsed = _maybe_uuid(value)
    return RepositoryId(parsed) if parsed is not None else None


def _maybe_project(value: object) -> ProjectId | None:
    parsed = _maybe_uuid(value)
    return ProjectId(parsed) if parsed is not None else None


def _maybe_uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _types_predicate(var: str, relation_types: list[RelationType] | None) -> str:
    if not relation_types:
        return "true"
    return " OR ".join(f"type({var}) = '{rt.value}'" for rt in relation_types)


def _rev_predicate(var: str, revision: str | None) -> str:
    if revision is None:
        return ""
    return f"AND ALL(rel IN {var} WHERE rel.revision = '{revision}')"


__all__ = ["Neo4jKnowledgeGraph", "Neo4jSettings", "neo4j_reachable"]
