"""Attachment content fetcher port.

Downloads the raw bytes of an attachment behind its ``download_url`` so
text-like attachments (Markdown, plain text, JSON) can be parsed and indexed
as documents.  PDF/DOCX content stays metadata-only until a document-conversion
capability (Docling) is enabled.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AttachmentContentFetcher(Protocol):
    async def fetch(self, url: str) -> bytes: ...


__all__ = ["AttachmentContentFetcher"]
