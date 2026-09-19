"""CommentRepository contract (Phase 0.1)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.comments import Comment, CommentKind
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import WorkItemId
from brain.ports.repositories import CommentRepository


def _comment() -> Comment:
    return Comment(
        work_item_id=WorkItemId(uuid.uuid4()),
        author_name="alice",
        text="hello",
        kind=CommentKind.FEEDBACK,
        external_refs=[
            ExternalReference(provider="openproject", external_id="42", external_type="activity")
        ],
    )


class CommentRepositoryContract:
    @pytest.fixture
    def comments(self) -> CommentRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, comments: CommentRepository) -> None:
        assert isinstance(comments, CommentRepository)

    async def test_save_and_get_round_trip(self, comments: CommentRepository) -> None:
        comment = _comment()
        await comments.create(comment)
        stored = await comments.get(comment.id)
        assert stored is not None
        assert stored.text == "hello"
        assert stored.kind == CommentKind.FEEDBACK
        assert stored.external_refs[0].external_id == "42"

    async def test_list_by_work_item(self, comments: CommentRepository) -> None:
        comment = _comment()
        await comments.create(comment)
        listed = await comments.list_by_work_item(comment.work_item_id)
        assert [c.id for c in listed] == [comment.id]

    async def test_find_by_external_ref(self, comments: CommentRepository) -> None:
        comment = _comment()
        await comments.create(comment)
        found = await comments.find_by_external_ref("openproject", "42", "activity")
        assert found is not None
        assert found.id == comment.id
        assert await comments.find_by_external_ref("openproject", "nope") is None
