"""Attachment domain model.

Canonical attachments attached to work-management entities (OpenProject work
package attachments).  Milestone 1 persists metadata and the download
reference; Markdown/text content is parsed, PDF/DOCX content is deferred until
a document-conversion capability (Docling) is enabled.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    AttachmentId,
    WorkItemId,
    new_attachment_id,
)


class Attachment(BaseModel):
    id: AttachmentId = Field(default_factory=new_attachment_id)
    work_item_id: WorkItemId
    file_name: str
    content_type: str = ""
    file_size: int | None = None
    download_url: str | None = None
    content_ingested: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    external_refs: list[ExternalReference] = Field(default_factory=list)


__all__ = ["Attachment"]
