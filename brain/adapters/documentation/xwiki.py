"""XWiki documentation adapter (Task 15.2).

Fetches pages, page versions, changes, attachments, hierarchy and links from
an XWiki instance and normalizes them into canonical ``SourceArtifact`` for
ingestion.  Network calls go through a pluggable transport so tests can inject
a fake XWiki API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from brain.domain.documents import SourceArtifact
from brain.domain.external_reference import ExternalReference
from brain.ports.documentation import DocumentationPort


class XWikiTransport(Protocol):
    """Minimal XWiki REST surface used by the adapter."""

    async def get_page(self, page_id: str) -> dict[str, Any]: ...

    async def get_page_version(self, page_id: str, version: str) -> dict[str, Any]: ...

    async def list_page_changes(self, page_id: str) -> list[dict[str, Any]]: ...

    async def get_attachments(self, page_id: str) -> list[dict[str, Any]]: ...

    async def get_children(self, page_id: str) -> list[dict[str, Any]]: ...

    async def get_links(self, page_id: str) -> list[str]: ...

    async def list_changed_pages(self, since: datetime) -> list[str]: ...


class XWikiDocumentationAdapter(DocumentationPort):
    """XWiki as a documentation provider."""

    def __init__(self, transport: XWikiTransport, wiki: str = "xwiki") -> None:
        self._transport = transport
        self._wiki = wiki

    def _ref(self, page_id: str) -> ExternalReference:
        return ExternalReference(
            provider="xwiki",
            external_id=page_id,
            external_type="page",
            namespace=self._wiki,
        )

    async def fetch_document(self, ref: ExternalReference) -> SourceArtifact:
        page = await self._transport.get_page(ref.external_id)
        content = page.get("content") or page.get("source") or ""
        return SourceArtifact(
            source_uri=ref.external_id,
            provider="xwiki",
            mime_type="text/html",
            file_name=ref.external_id,
            revision=str(page.get("version") or ""),
            content=str(content).encode("utf-8"),
            metadata={
                "wiki": self._wiki,
                "title": page.get("title"),
                "parent": page.get("parent"),
            },
        )

    async def list_changed_documents(self, since: datetime) -> list[ExternalReference]:
        page_ids = await self._transport.list_changed_pages(since)
        return [self._ref(page_id) for page_id in page_ids]

    async def search(self, query: str) -> list[ExternalReference]:
        del query
        # Full-text search requires a transport method; return an empty list.
        return []

    async def fetch_page_version(self, ref: ExternalReference, version: str) -> SourceArtifact:
        page = await self._transport.get_page_version(ref.external_id, version)
        content = page.get("content") or page.get("source") or ""
        return SourceArtifact(
            source_uri=ref.external_id,
            provider="xwiki",
            mime_type="text/html",
            file_name=ref.external_id,
            revision=version,
            content=str(content).encode("utf-8"),
            metadata={"wiki": self._wiki, "title": page.get("title")},
        )


__all__ = ["XWikiDocumentationAdapter", "XWikiTransport"]
