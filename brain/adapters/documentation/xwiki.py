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
from brain.ports.provisioning import DocumentationProvisioningPort


class XWikiTransport(Protocol):
    """Minimal XWiki REST surface used by the adapter."""

    async def get_page(self, page_id: str) -> dict[str, Any]: ...

    async def get_page_version(self, page_id: str, version: str) -> dict[str, Any]: ...

    async def list_page_changes(self, page_id: str) -> list[dict[str, Any]]: ...

    async def get_attachments(self, page_id: str) -> list[dict[str, Any]]: ...

    async def get_children(self, page_id: str) -> list[dict[str, Any]]: ...

    async def get_links(self, page_id: str) -> list[str]: ...

    async def list_changed_pages(
        self,
        spaces: list[str],
        since: datetime | None = None,
        *,
        page_size: int = 50,
    ) -> list[dict[str, Any]]: ...

    async def create_space(self, space: str) -> dict[str, Any]: ...


class XWikiDocumentationAdapter(DocumentationPort, DocumentationProvisioningPort):
    """XWiki as a documentation provider + space provisioner."""

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

    async def create_space(self, name: str) -> ExternalReference:
        """Create a wiki space and return its external reference (Phase 2.3)."""
        await self._transport.create_space(name)
        return ExternalReference(
            provider="xwiki",
            external_id=name,
            external_type="space",
            namespace=self._wiki,
        )

    async def fetch_document(self, ref: ExternalReference) -> SourceArtifact:
        page = await self._transport.get_page(ref.external_id)
        return self._to_artifact(page, ref)

    async def list_changed_documents(
        self,
        since: datetime | None = None,
        *,
        spaces: list[str] | None = None,
    ) -> list[ExternalReference]:
        """List pages in the given spaces modified after ``since``.

        Spaces are required (the mapped spaces of the canonical projects);
        without them nothing can be discovered.
        """
        if not spaces:
            return []
        pages = await self._transport.list_changed_pages(spaces, since)
        return [self._ref(str(page.get("id"))) for page in pages if page.get("id")]

    async def search(self, query: str) -> list[ExternalReference]:
        del query
        # Full-text search requires a transport method; return an empty list.
        return []

    async def fetch_page_version(self, ref: ExternalReference, version: str) -> SourceArtifact:
        page = await self._transport.get_page_version(ref.external_id, version)
        return self._to_artifact(page, ref, revision=version)

    def _to_artifact(
        self,
        page: dict[str, Any],
        ref: ExternalReference,
        *,
        revision: str | None = None,
    ) -> SourceArtifact:
        """Normalize a flattened XWiki page into a canonical SourceArtifact.

        XWiki REST serves the page content in its native ``xwiki/2.1`` syntax
        (never converted HTML), so the artifact is labelled ``text/x-xwiki``
        and parsed by :class:`XWikiSyntaxParser` (Step 2).
        """
        content = page.get("content") or page.get("source") or ""
        syntax = page.get("syntax") or "xwiki/2.1"
        return SourceArtifact(
            source_uri=ref.external_id,
            provider="xwiki",
            mime_type="text/x-xwiki",
            file_name=ref.external_id,
            revision=revision or str(page.get("version") or ""),
            content=str(content).encode("utf-8"),
            metadata={
                "wiki": self._wiki,
                "title": page.get("title"),
                "parent": page.get("parent"),
                "space": page.get("space") or _space_of(ref.external_id),
                "syntax": syntax,
                "modified": page.get("modified"),
            },
        )


__all__ = ["XWikiDocumentationAdapter", "XWikiTransport"]


def _space_of(page_id: str) -> str:
    """Extract the space from a dotted page reference (``ADAS.PageName``)."""
    parts = page_id.split(".")
    return parts[0] if parts and parts[0] else page_id
