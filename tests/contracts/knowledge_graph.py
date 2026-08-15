"""KnowledgeGraphRepository contract."""

from __future__ import annotations

import uuid

import pytest

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
        auth = GraphEntity(id=uuid.uuid4(), label="SoftwareComponent", properties={"name": "auth"})
        repo = GraphEntity(id=uuid.uuid4(), label="Repository", properties={"name": "auth-service"})
        file = GraphEntity(id=uuid.uuid4(), label="File", properties={"path": "services/auth.py"})
        await knowledge_graph.upsert_entities([auth, repo, file])
        await knowledge_graph.upsert_relations(
            [
                GraphRelation(subject_id=auth.id, relation_type="PART_OF", object_id=repo.id),
                GraphRelation(subject_id=repo.id, relation_type="CONTAINS", object_id=file.id),
            ]
        )

        reached = await knowledge_graph.traverse([auth.id], ["PART_OF", "CONTAINS"], depth=2)
        ids = {e.id for e in reached}
        assert auth.id in ids
        assert repo.id in ids
        assert file.id in ids

    async def test_traverse_respects_relation_types(
        self, knowledge_graph: KnowledgeGraphRepository
    ) -> None:
        a = GraphEntity(id=uuid.uuid4(), label="Symbol")
        b = GraphEntity(id=uuid.uuid4(), label="Symbol")
        await knowledge_graph.upsert_entities([a, b])
        await knowledge_graph.upsert_relations(
            [GraphRelation(subject_id=a.id, relation_type="CALLS", object_id=b.id)]
        )
        # No IMPORTS relations exist: only the start node is reachable.
        reached = await knowledge_graph.traverse([a.id], ["IMPORTS"], depth=1)
        assert {e.id for e in reached} == {a.id}
        reached = await knowledge_graph.traverse([a.id], ["CALLS"], depth=1)
        assert {e.id for e in reached} == {a.id, b.id}

    async def test_traverse_does_not_follow_missing_nodes(
        self, knowledge_graph: KnowledgeGraphRepository
    ) -> None:
        start = uuid.uuid4()
        ghost = uuid.uuid4()
        await knowledge_graph.upsert_relations(
            [GraphRelation(subject_id=start, relation_type="CALLS", object_id=ghost)]
        )
        reached = await knowledge_graph.traverse([start], ["CALLS"], depth=1)
        assert {e.id for e in reached} == set()
