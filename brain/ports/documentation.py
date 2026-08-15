"""Documentation port (XWiki / Confluence / Git Markdown / ...).

Provider documents are normalized into ``SourceArtifact`` for ingestion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from brain.domain.documents import SourceArtifact
from brain.domain.external_reference import ExternalReference


@runtime_checkable
class DocumentationPort(Protocol):
    async def fetch_document(self, ref: ExternalReference) -> SourceArtifact: ...

    async def list_changed_documents(self, since: datetime) -> list[ExternalReference]: ...

    async def search(self, query: str) -> list[ExternalReference]: ...
