"""Git Markdown documentation adapter (Task 15.1).

Treats repository documentation as a ``DocumentationPort`` provider: fetch a
document at a revision, list changed docs since a date, and search.  Uses the
``SourceControlPort`` behind a thin transport so local git and remote providers
both work.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from brain.domain.documents import SourceArtifact
from brain.domain.external_reference import ExternalReference
from brain.domain.repositories import Repository
from brain.ports.documentation import DocumentationPort

_DOC_EXTENSIONS = (".md", ".markdown", ".rst", ".adoc", ".txt")


class GitMarkdownTransport(Protocol):
    """Revision-aware file reading for the adapter."""

    async def read_file(self, repository: Repository, path: str, revision: str) -> bytes: ...

    async def tree(self, repository: Repository, revision: str) -> list[str]: ...


class GitMarkdownDocumentationAdapter(DocumentationPort):
    """Repository docs as a documentation provider."""

    def __init__(
        self,
        *,
        repository: Repository,
        transport: GitMarkdownTransport,
        revision: str | None = None,
    ) -> None:
        self._repository = repository
        self._transport = transport
        self._revision = revision or ""

    def _ref(self, path: str) -> ExternalReference:
        return ExternalReference(
            provider="git_markdown",
            external_id=path,
            external_type="document",
            namespace=self._repository.name,
        )

    async def fetch_document(self, ref: ExternalReference) -> SourceArtifact:
        content = await self._transport.read_file(self._repository, ref.external_id, self._revision)
        return SourceArtifact(
            source_uri=ref.external_id,
            provider="git_markdown",
            mime_type=_mime_type(ref.external_id),
            file_name=ref.external_id.rsplit("/", 1)[-1],
            revision=self._revision or None,
            content=content,
            metadata={"repository": self._repository.name},
        )

    async def list_changed_documents(self, since: datetime) -> list[ExternalReference]:
        del since
        paths = await self._transport.tree(self._repository, self._revision)
        refs: list[ExternalReference] = []
        for path in paths:
            if path.lower().endswith(_DOC_EXTENSIONS):
                refs.append(self._ref(path))
        return refs

    async def search(self, query: str) -> list[ExternalReference]:
        del query
        paths = await self._transport.tree(self._repository, self._revision)
        return [self._ref(path) for path in paths if path.lower().endswith(_DOC_EXTENSIONS)]


def _mime_type(path: str) -> str | None:
    if path.endswith(".md") or path.endswith(".markdown"):
        return "text/markdown"
    if path.endswith(".rst"):
        return "text/x-rst"
    if path.endswith(".adoc"):
        return "text/asciidoc"
    if path.endswith(".txt"):
        return "text/plain"
    return None


__all__ = ["GitMarkdownDocumentationAdapter", "GitMarkdownTransport"]
