"""WorkItemRelationRepository contract (Phase 0.3)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import WorkItemId
from brain.domain.work_item_relations import WorkItemRelation, WorkItemRelationType
from brain.ports.repositories import WorkItemRelationRepository


def _relation() -> WorkItemRelation:
    return WorkItemRelation(
        source_work_item_id=WorkItemId(uuid.uuid4()),
        target_work_item_id=WorkItemId(uuid.uuid4()),
        relation_type=WorkItemRelationType.BLOCKS,
    )


class WorkItemRelationRepositoryContract:
    @pytest.fixture
    def relations(self) -> WorkItemRelationRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, relations: WorkItemRelationRepository) -> None:
        assert isinstance(relations, WorkItemRelationRepository)

    async def test_save_and_list_by_work_item(self, relations: WorkItemRelationRepository) -> None:
        relation = _relation()
        await relations.create(relation)
        listed = await relations.list_by_work_item(relation.source_work_item_id)
        assert [r.id for r in listed] == [relation.id]
        assert listed[0].relation_type == WorkItemRelationType.BLOCKS
        # Target side is listed too.
        assert [r.id for r in await relations.list_by_work_item(relation.target_work_item_id)] == [
            relation.id
        ]

    async def test_upsert_is_idempotent_for_same_triple(
        self, relations: WorkItemRelationRepository
    ) -> None:
        relation = _relation()
        await relations.create(relation)
        await relations.create(relation)
        listed = await relations.list_by_work_item(relation.source_work_item_id)
        assert len(listed) == 1

    async def test_delete(self, relations: WorkItemRelationRepository) -> None:
        relation = _relation()
        await relations.create(relation)
        await relations.delete(relation.id)
        assert await relations.list_by_work_item(relation.source_work_item_id) == []
