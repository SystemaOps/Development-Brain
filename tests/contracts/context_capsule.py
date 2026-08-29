"""ContextCapsuleRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.context import (
    CodingContextCapsule,
    ContextCandidate,
    ContextCategory,
    ContextRequest,
    RetrievalSource,
)
from brain.domain.identity import WorkItemId, new_work_item_id
from brain.ports.context import ContextCapsuleRepository


def _capsule(work_item_id: WorkItemId) -> CodingContextCapsule:
    request = ContextRequest(work_item_id=work_item_id, preferred_token_budget=1000)
    return CodingContextCapsule(
        work_item_id=work_item_id,
        request=request,
        candidates=[
            ContextCandidate(
                entity_id=work_item_id,
                entity_type="WorkItem",
                content="task",
                reason="primary",
                retrieval_source=RetrievalSource.WORK_ITEM,
                category=ContextCategory.TASK,
            )
        ],
        total_tokens=50,
        model_budget_tokens=1000,
    )


class ContextCapsuleRepositoryContract:
    @pytest.fixture
    def capsule_repository(self) -> ContextCapsuleRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, capsule_repository: ContextCapsuleRepository) -> None:
        assert isinstance(capsule_repository, ContextCapsuleRepository)

    async def test_save_and_get_round_trip(
        self, capsule_repository: ContextCapsuleRepository
    ) -> None:
        work_item_id = new_work_item_id()
        capsule = _capsule(work_item_id)
        await capsule_repository.save_capsule(capsule)
        stored = await capsule_repository.get_capsule(capsule.id)
        assert stored is not None
        assert stored.id == capsule.id
        assert stored.work_item_id == work_item_id
        assert stored.total_tokens == 50

    async def test_list_by_work_item(self, capsule_repository: ContextCapsuleRepository) -> None:
        work_item_id = new_work_item_id()
        await capsule_repository.save_capsule(_capsule(work_item_id))
        await capsule_repository.save_capsule(_capsule(work_item_id))
        capsules = await capsule_repository.list_capsules_for_work_item(work_item_id)
        assert len(capsules) == 2

    async def test_delete(self, capsule_repository: ContextCapsuleRepository) -> None:
        work_item_id = new_work_item_id()
        capsule = _capsule(work_item_id)
        await capsule_repository.save_capsule(capsule)
        await capsule_repository.delete_capsule(capsule.id)
        assert await capsule_repository.get_capsule(capsule.id) is None

    async def test_missing_capsule_returns_none(
        self, capsule_repository: ContextCapsuleRepository
    ) -> None:
        assert await capsule_repository.get_capsule(_capsule(new_work_item_id()).id) is None
