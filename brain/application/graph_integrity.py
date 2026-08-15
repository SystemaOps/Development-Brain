"""Knowledge graph integrity checks (Task 8.7).

Detect the failure modes the plan calls out: duplicate canonical nodes, orphan
external ids, invalid revision scope, and unknown relation types.  The checker
works purely over the port's read API so it runs against the in-memory
reference graph and Neo4j alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.domain.graph_schema import RelationType
from brain.domain.identity import ProjectId
from brain.ports.knowledge_graph import GraphEntity, KnowledgeGraphRepository


@dataclass
class IntegrityIssue:
    category: str
    detail: str


@dataclass
class GraphIntegrityReport:
    project_id: ProjectId | None = None
    issues: list[IntegrityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


class GraphIntegrityChecker:
    """Check a knowledge graph for structural integrity problems."""

    def __init__(self, *, graph: KnowledgeGraphRepository) -> None:
        self._graph = graph

    async def check(self, project_id: ProjectId | None = None) -> GraphIntegrityReport:
        report = GraphIntegrityReport(project_id=project_id)
        entities = await self._graph.find_entities(project_id=project_id)

        # 1. Duplicate canonical nodes: same label + same canonical identity.
        #    Symbols are identified by qualified name; files by path; other
        #    entities by their id (projection keeps ids stable).
        seen: dict[tuple[str, str], int] = {}
        for entity in entities:
            key_name = _entity_identity(entity)
            key = (entity.label.value, key_name)
            seen[key] = seen.get(key, 0) + 1
        for (label, name), count in seen.items():
            if count > 1:
                report.issues.append(
                    IntegrityIssue("duplicate_node", f"{label} '{name}' appears {count} times")
                )

        # 2. Orphan references: relations pointing to missing nodes.
        entity_ids = {entity.id for entity in entities}
        relations = await self._graph.find_relations()
        for relation in relations:
            if relation.subject_id not in entity_ids:
                report.issues.append(
                    IntegrityIssue(
                        "orphan_subject", f"relation {relation.relation_type.value} subject missing"
                    )
                )
            if relation.object_id not in entity_ids:
                report.issues.append(
                    IntegrityIssue(
                        "orphan_object", f"relation {relation.relation_type.value} object missing"
                    )
                )

        # 3. Invalid revision scope: entity has revision but relation to it lacks it.
        revisioned_entities = {e.id for e in entities if e.revision is not None}
        for relation in relations:
            if relation.subject_id in revisioned_entities and relation.revision is None:
                report.issues.append(
                    IntegrityIssue(
                        "invalid_revision_scope",
                        f"relation {relation.relation_type.value} revision missing",
                    )
                )

        # 4. Unknown relation types (not in the controlled vocabulary).
        known_types = {rt.value for rt in RelationType}
        for relation in relations:
            if relation.relation_type.value not in known_types:
                report.issues.append(
                    IntegrityIssue(
                        "unknown_relation_type",
                        f"type '{relation.relation_type.value}' not controlled",
                    )
                )

        return report


def _entity_identity(entity: GraphEntity) -> str:
    """Canonical identity used for duplicate-node detection."""
    if entity.label.value == "Symbol":
        return str(entity.properties.get("qualified_name") or entity.id)
    if entity.label.value == "File":
        return str(entity.properties.get("path") or entity.id)
    if entity.label.value in {"Component", "Repository"}:
        return str(entity.properties.get("name") or entity.id)
    return str(entity.id)


__all__ = ["GraphIntegrityChecker", "GraphIntegrityReport", "IntegrityIssue"]
