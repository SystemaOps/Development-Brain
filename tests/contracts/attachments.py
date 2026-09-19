"""AttachmentRepository contract (Phase 0.1)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.attachments import Attachment
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import WorkItemId
from brain.ports.repositories import AttachmentRepository


def _attachment() -> Attachment:
    return Attachment(
        work_item_id=WorkItemId(uuid.uuid4()),
        file_name="spec.pdf",
        content_type="application/pdf",
        file_size=1024,
        download_url="https://op.example/download/7",
        external_refs=[
            ExternalReference(provider="openproject", external_id="7", external_type="attachment")
        ],
    )


class AttachmentRepositoryContract:
    @pytest.fixture
    def attachments(self) -> AttachmentRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, attachments: AttachmentRepository) -> None:
        assert isinstance(attachments, AttachmentRepository)

    async def test_save_and_get_round_trip(self, attachments: AttachmentRepository) -> None:
        attachment = _attachment()
        await attachments.create(attachment)
        stored = await attachments.get(attachment.id)
        assert stored is not None
        assert stored.file_name == "spec.pdf"
        assert stored.download_url is not None
        assert stored.content_ingested is False

    async def test_list_by_work_item(self, attachments: AttachmentRepository) -> None:
        attachment = _attachment()
        await attachments.create(attachment)
        listed = await attachments.list_by_work_item(attachment.work_item_id)
        assert [a.id for a in listed] == [attachment.id]

    async def test_find_by_external_ref(self, attachments: AttachmentRepository) -> None:
        attachment = _attachment()
        await attachments.create(attachment)
        found = await attachments.find_by_external_ref("openproject", "7", "attachment")
        assert found is not None
        assert found.id == attachment.id
        assert await attachments.find_by_external_ref("openproject", "nope") is None
