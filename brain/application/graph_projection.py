"""Graph projection service (Task 8.5).

Projects canonical PostgreSQL entities into the knowledge graph so cross-domain
relationships (requirement -> work item -> component -> repository -> file ->
symbol -> test, decision -> component) can be traversed for context
construction.  The projection reads through ports only and writes through the
:class:`KnowledgeGraphRepository` port, so the same service works against the
in-memory reference graph or Neo4j.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from brain.domain.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    is_test_path,
)
from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.projects import Project
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.knowledge_graph import (
    GraphEntity,
    GraphRelation,
    KnowledgeGraphRepository,
)
from brain.ports.repositories import (
    DecisionRepository,
    RepositoryRepository,
    RequirementRepository,
    WorkItemRepository,
)
from brain.ports.topology import SoftwareCatalogRepository


@dataclass
class GraphProjectionResult:
    project_id: ProjectId
    entities: list[GraphEntity] = field(default_factory=list)
    relations: list[GraphRelation] = field(default_factory=list)


class GraphProjectionService:
    """Project canonical state into the knowledge graph (Task 8.5)."""

    def __init__(
        self,
        *,
        graph: KnowledgeGraphRepository,
        projects: object,
        requirements: RequirementRepository,
        work_items: WorkItemRepository,
        repositories: RepositoryRepository,
        catalog: SoftwareCatalogRepository,
        decisions: DecisionRepository,
        code_graph: CodeGraphRepository,
    ) -> None:
        del projects
        self._graph = graph
        self._requirements = requirements
        self._work_items = work_items
        self._repositories = repositories
        self._catalog = catalog
        self._decisions = decisions
        self._code_graph = code_graph

    async def project(
        self,
        project: Project,
        *,
        revision: str | None = None,
    ) -> GraphProjectionResult:
        entities: list[GraphEntity] = []
        relations: list[GraphRelation] = []

        project_node = GraphEntity(
            id=project.id,
            label=GraphLabel.PROJECT,
            project_id=project.id,
            properties={"name": project.name},
            revision=revision,
        )
        entities.append(project_node)

        repository_ids: list[RepositoryId] = []
        for repository in await self._repositories.list_by_project(project.id):
            repo_node = GraphEntity(
                id=repository.id,
                label=GraphLabel.REPOSITORY,
                project_id=project.id,
                repository_id=repository.id,
                properties={"name": repository.name, "clone_url": repository.clone_url},
                revision=revision,
            )
            entities.append(repo_node)
            repository_ids.append(repository.id)
            relations.append(
                GraphRelation(
                    subject_id=project.id,
                    relation_type=RelationType.PART_OF,
                    object_id=repository.id,
                    revision=revision,
                )
            )

        requirement_nodes: list[GraphEntity] = []
        for requirement in await self._requirements.list_by_project(project.id):
            requirement_node = GraphEntity(
                id=requirement.id,
                label=GraphLabel.REQUIREMENT,
                project_id=project.id,
                properties={
                    "key": requirement.key or "",
                    "title": requirement.title,
                    "status": _as_str(requirement.status),
                },
                revision=revision,
            )
            entities.append(requirement_node)
            requirement_nodes.append(requirement_node)
            relations.append(
                GraphRelation(
                    subject_id=requirement.id,
                    relation_type=RelationType.PART_OF,
                    object_id=project.id,
                    revision=revision,
                )
            )
            if requirement.parent_id:
                relations.append(
                    GraphRelation(
                        subject_id=requirement.id,
                        relation_type=RelationType.DERIVED_FROM,
                        object_id=requirement.parent_id,
                        revision=revision,
                    )
                )

        for work_item in await self._work_items.list_by_project(project.id):
            entities.append(
                GraphEntity(
                    id=work_item.id,
                    label=GraphLabel.WORK_ITEM,
                    project_id=project.id,
                    properties={
                        "title": work_item.title,
                        "type": _as_str(work_item.type),
                        "implementation_status": _as_str(work_item.implementation_status),
                    },
                    revision=revision,
                )
            )
            relations.append(
                GraphRelation(
                    subject_id=work_item.id,
                    relation_type=RelationType.PART_OF,
                    object_id=project.id,
                    revision=revision,
                )
            )
            for requirement_ref in work_item.requirement_refs:
                relations.append(
                    GraphRelation(
                        subject_id=work_item.id,
                        relation_type=RelationType.IMPLEMENTS,
                        object_id=requirement_ref,
                        revision=revision,
                    )
                )

        component_by_name: dict[str, GraphEntity] = {}
        for component in await self._catalog.list_components(project.id):
            component_node = GraphEntity(
                id=component.id,
                label=GraphLabel.COMPONENT,
                project_id=project.id,
                properties={
                    "name": component.name,
                    "component_type": _as_str(component.component_type),
                },
                revision=revision,
            )
            entities.append(component_node)
            component_by_name[component.name] = component_node
            relations.append(
                GraphRelation(
                    subject_id=component_node.id,
                    relation_type=RelationType.PART_OF,
                    object_id=project.id,
                    revision=revision,
                )
            )
            for repository_id in component.repository_ids:
                relations.append(
                    GraphRelation(
                        subject_id=component_node.id,
                        relation_type=RelationType.DEPENDS_ON,
                        object_id=repository_id,
                        revision=revision,
                    )
                )

        # Requirement -> Component: link when the requirement mentions the
        # component by name (conservative keyword match), enabling the
        # task -> requirement -> component traversal.
        for requirement_node in requirement_nodes:
            requirement_text = " ".join(
                [
                    str(requirement_node.properties.get("key", "")),
                    str(requirement_node.properties.get("title", "")),
                ]
            ).lower()
            for component_name, component_node in component_by_name.items():
                if component_name and component_name.lower() in requirement_text:
                    relations.append(
                        GraphRelation(
                            subject_id=requirement_node.id,
                            relation_type=RelationType.REFERENCES,
                            object_id=component_node.id,
                            revision=revision,
                        )
                    )

        for decision in await self._decisions.list_by_project(project.id):
            entities.append(
                GraphEntity(
                    id=decision.id,
                    label=GraphLabel.DECISION,
                    project_id=project.id,
                    properties={"title": decision.title, "status": _as_str(decision.status)},
                    revision=revision,
                )
            )
            relations.append(
                GraphRelation(
                    subject_id=decision.id,
                    relation_type=RelationType.PART_OF,
                    object_id=project.id,
                    revision=revision,
                )
            )
            # Decision -> Component: link by name when a component matches the
            # decision's context/title keywords (conservative).
            for component_name, component_node in component_by_name.items():
                if component_name and component_name.lower() in decision.title.lower():
                    relations.append(
                        GraphRelation(
                            subject_id=decision.id,
                            relation_type=RelationType.REFERENCES,
                            object_id=component_node.id,
                            revision=revision,
                        )
                    )

        for repository_id in repository_ids:
            if revision is None:
                continue
            await self._project_code_graph(
                entities,
                relations,
                project.id,
                repository_id,
                revision,
            )

        await self._graph.upsert_entities(entities)
        await self._graph.upsert_relations(relations)
        return GraphProjectionResult(project_id=project.id, entities=entities, relations=relations)

    async def _project_code_graph(
        self,
        entities: list[GraphEntity],
        relations: list[GraphRelation],
        project_id: ProjectId,
        repository_id: RepositoryId,
        revision: str,
    ) -> None:
        symbols = await self._code_graph.list_symbols(repository_id, revision)
        code_relations = await self._code_graph.list_relations(repository_id, revision)

        file_nodes: dict[str, GraphEntity] = {}
        symbol_nodes: dict[str, GraphEntity] = {}
        for symbol in symbols:
            file_path = symbol.path
            if file_path not in file_nodes:
                is_test = symbol.metadata.get("is_test", False) or is_test_path(file_path)
                file_label = GraphLabel.TEST if is_test else GraphLabel.FILE
                file_node = GraphEntity(
                    id=_file_entity_id(repository_id, revision, file_path),
                    label=file_label,
                    project_id=project_id,
                    repository_id=repository_id,
                    properties={"path": file_path, "module": symbol.identity.module},
                    revision=revision,
                )
                entities.append(file_node)
                file_nodes[file_path] = file_node
                relations.append(
                    GraphRelation(
                        subject_id=file_node.id,
                        relation_type=RelationType.PART_OF,
                        object_id=repository_id,
                        revision=revision,
                    )
                )
            symbol_node = GraphEntity(
                id=symbol.id,
                label=GraphLabel.SYMBOL,
                project_id=project_id,
                repository_id=repository_id,
                properties={
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "kind": _as_str(symbol.kind),
                },
                revision=revision,
            )
            entities.append(symbol_node)
            symbol_nodes[symbol.identity_key] = symbol_node
            relations.append(
                GraphRelation(
                    subject_id=symbol_node.id,
                    relation_type=RelationType.PART_OF,
                    object_id=file_nodes[file_path].id,
                    revision=revision,
                )
            )
            if symbol.kind.value == "class":
                relations.append(
                    GraphRelation(
                        subject_id=symbol_node.id,
                        relation_type=RelationType.PART_OF,
                        object_id=file_nodes[file_path].id,
                        revision=revision,
                    )
                )

        for relation in code_relations:
            source = symbol_nodes.get(relation.source_identity.key)
            target = symbol_nodes.get(relation.target_identity.key)
            if source is None or target is None:
                continue
            relations.append(
                GraphRelation(
                    subject_id=source.id,
                    relation_type=_map_code_relation(relation),
                    object_id=target.id,
                    repository_id=repository_id,
                    revision=revision,
                    properties={"confidence": relation.confidence},
                )
            )


def _as_str(value: object) -> str:
    return str(getattr(value, "value", value))


def _file_entity_id(repository_id: RepositoryId, revision: str, path: str) -> uuid.UUID:
    """Deterministic graph node id for a file so re-projections are idempotent."""
    import hashlib

    digest = hashlib.sha256(f"{repository_id}:{revision}:{path}".encode()).hexdigest()[:32]
    return uuid.UUID(digest)


def _map_code_relation(relation: CodeRelation) -> RelationType:
    mapping = {
        CodeRelationType.IMPORTS: RelationType.IMPORTS,
        CodeRelationType.CALLS: RelationType.CALLS,
        CodeRelationType.INSTANTIATES: RelationType.REFERENCES,
        CodeRelationType.INHERITS: RelationType.DERIVED_FROM,
        CodeRelationType.OVERRIDES: RelationType.REFERENCES,
        CodeRelationType.READS: RelationType.READS,
        CodeRelationType.WRITES: RelationType.WRITES,
        CodeRelationType.TESTS: RelationType.TESTS,
    }
    return mapping.get(relation.relation_type, RelationType.REFERENCES)


__all__ = ["GraphProjectionResult", "GraphProjectionService"]
