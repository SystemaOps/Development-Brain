"""KnowledgeGraphRepository contract."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.identity import ProjectId
from brain.ports.knowledge_graph import (
    GraphEntity,
    GraphRelation,
    KnowledgeGraphRepository,
)


class KnowledgeGraphRepositoryContract:
    @pytest.fixture
    def knowledge_graph(self) -> KnowledgeGraphRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, knowledge_graph: KnowledgeGraphRepository) -> None:
        assert isinstance(knowledge_graph, KnowledgeGraphRepository)

    async def test_upsert_and_traverse(self, knowledge_graph: KnowledgeGraphRepository) -> None:
        auth = GraphEntity(id=uuid.uuid4(), label=GraphLabel.COMPONENT, properties={"name": "auth"})
        repo = GraphEntity(
            id=uuid.uuid4(), label=GraphLabel.REPOSITORY, properties={"name": "auth-service"}
        )
        file = GraphEntity(
            id=uuid.uuid4(), label=GraphLabel.FILE, properties={"path": "services/auth.py"}
        )
        await knowledge_graph.upsert_entities([auth, repo, file])
        await knowledge_graph.upsert_relations(
            [
                GraphRelation(
                    subject_id=auth.id, relation_type=RelationType.PART_OF, object_id=repo.id
                ),
                GraphRelation(
                    subject_id=repo.id, relation_type=RelationType.PART_OF, object_id=file.id
                ),
            ]
        )

        reached = await knowledge_graph.traverse([auth.id], [RelationType.PART_OF], depth=2)
        ids = {e.id for e in reached}
        assert auth.id in ids
        assert repo.id in ids
        assert file.id in ids

    async def test_traverse_respects_relation_types(
        self, knowledge_graph: KnowledgeGraphRepository
    ) -> None:
        a = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        b = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        await knowledge_graph.upsert_entities([a, b])
        await knowledge_graph.upsert_relations(
            [GraphRelation(subject_id=a.id, relation_type=RelationType.CALLS, object_id=b.id)]
        )
        reached = await knowledge_graph.traverse([a.id], [RelationType.IMPORTS], depth=1)
        assert {e.id for e in reached} == {a.id}
        reached = await knowledge_graph.traverse([a.id], [RelationType.CALLS], depth=1)
        assert {e.id for e in reached} == {a.id, b.id}

    async def test_traverse_does_not_follow_missing_nodes(
        self, knowledge_graph: KnowledgeGraphRepository
    ) -> None:
        start = uuid.uuid4()
        ghost = uuid.uuid4()
        await knowledge_graph.upsert_relations(
            [GraphRelation(subject_id=start, relation_type=RelationType.CALLS, object_id=ghost)]
        )
        reached = await knowledge_graph.traverse([start], [RelationType.CALLS], depth=1)
        assert {e.id for e in reached} == set()

    async def test_traverse_reverse_finds_callers(
        self, knowledge_graph: KnowledgeGraphRepository
    ) -> None:
        caller = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        callee = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        await knowledge_graph.upsert_entities([caller, callee])
        await knowledge_graph.upsert_relations(
            [
                GraphRelation(
                    subject_id=caller.id, relation_type=RelationType.CALLS, object_id=callee.id
                )
            ]
        )
        reached = await knowledge_graph.traverse_reverse([callee.id], [RelationType.CALLS], depth=1)
        ids = {e.id for e in reached}
        assert caller.id in ids
        assert callee.id in ids

    async def test_neighborhood_both_directions(
        self, knowledge_graph: KnowledgeGraphRepository
    ) -> None:
        a = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        b = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        await knowledge_graph.upsert_entities([a, b])
        await knowledge_graph.upsert_relations(
            [GraphRelation(subject_id=a.id, relation_type=RelationType.CALLS, object_id=b.id)]
        )
        reached = await knowledge_graph.neighborhood([b.id], [RelationType.CALLS], direction="both")
        ids = {e.id for e in reached}
        assert a.id in ids
        assert b.id in ids

    async def test_find_entities_filters(self, knowledge_graph: KnowledgeGraphRepository) -> None:
        project_id = ProjectId(uuid.uuid4())
        comp = GraphEntity(
            id=uuid.uuid4(),
            label=GraphLabel.COMPONENT,
            project_id=project_id,
            properties={"name": "auth"},
        )
        repo = GraphEntity(
            id=uuid.uuid4(),
            label=GraphLabel.REPOSITORY,
            project_id=project_id,
            properties={"name": "r"},
        )
        await knowledge_graph.upsert_entities([comp, repo])
        by_label = await knowledge_graph.find_entities(GraphLabel.COMPONENT, project_id=project_id)
        assert [e.id for e in by_label] == [comp.id]
        by_project = await knowledge_graph.find_entities(project_id=project_id)
        assert len(by_project) == 2

    async def test_find_relations_filters(self, knowledge_graph: KnowledgeGraphRepository) -> None:
        a = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        b = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        c = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        await knowledge_graph.upsert_entities([a, b, c])
        await knowledge_graph.upsert_relations(
            [
                GraphRelation(subject_id=a.id, relation_type=RelationType.CALLS, object_id=b.id),
                GraphRelation(subject_id=a.id, relation_type=RelationType.IMPORTS, object_id=c.id),
            ]
        )
        calls = await knowledge_graph.find_relations(RelationType.CALLS)
        assert len(calls) == 1
        assert calls[0].object_id == b.id
        subject = await knowledge_graph.find_relations(subject_id=a.id)
        assert len(subject) == 2
        object_filtered = await knowledge_graph.find_relations(object_id=c.id)
        assert len(object_filtered) == 1

    async def test_revision_filter_on_relations(
        self, knowledge_graph: KnowledgeGraphRepository
    ) -> None:
        a = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        b = GraphEntity(id=uuid.uuid4(), label=GraphLabel.SYMBOL)
        await knowledge_graph.upsert_entities([a, b])
        await knowledge_graph.upsert_relations(
            [
                GraphRelation(
                    subject_id=a.id,
                    relation_type=RelationType.CALLS,
                    object_id=b.id,
                    revision="abc",
                ),
                GraphRelation(
                    subject_id=a.id,
                    relation_type=RelationType.CALLS,
                    object_id=b.id,
                    revision="def",
                ),
            ]
        )
        reached = await knowledge_graph.traverse(
            [a.id], [RelationType.CALLS], depth=1, revision="abc"
        )
        # Both relations share subject/object; the revision filter keeps them
        # identical here, but the relation-level filter must return only abc.
        assert b.id in {e.id for e in reached}
        relations = await knowledge_graph.find_relations(RelationType.CALLS, revision="def")
        assert len(relations) == 1
        assert relations[0].revision == "def"
