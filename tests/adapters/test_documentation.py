"""Run the DocumentationPort contract against the Git Markdown and XWiki adapters."""

from __future__ import annotations

from datetime import datetime

import pytest

from brain.adapters.documentation.git_markdown import (
    GitMarkdownDocumentationAdapter,
)
from brain.adapters.documentation.xwiki import XWikiDocumentationAdapter
from brain.domain.identity import new_project_id
from brain.domain.repositories import Repository
from brain.ports.documentation import DocumentationPort
from tests.contracts.documentation import DocumentationPortContract


class _FakeGitTransport:
    async def read_file(self, repository: Repository, path: str, revision: str) -> bytes:
        return f"# {path}\ncontent\n".encode()

    async def tree(self, repository: Repository, revision: str) -> list[str]:
        return ["README.md", "docs/architecture.md", "app/main.py"]


class TestGitMarkdownDocumentationAdapter(DocumentationPortContract):
    @pytest.fixture
    def documentation_provider(self) -> str:
        return "git_markdown"

    @pytest.fixture
    def documentation(self) -> DocumentationPort:
        repository = Repository(
            project_id=new_project_id(), name="auth", clone_url="git@example:auth.git"
        )
        return GitMarkdownDocumentationAdapter(
            repository=repository, transport=_FakeGitTransport(), revision="abc"
        )


class _FakeXWiki:
    async def get_page(self, page_id: str) -> dict:
        return {
            "id": page_id,
            "title": f"Page {page_id}",
            "version": "3",
            "content": "<h1>Hello</h1><p>world</p>",
        }

    async def get_page_version(self, page_id: str, version: str) -> dict:
        return {"id": page_id, "title": f"Page {page_id}", "version": version, "content": "x"}

    async def list_page_changes(self, page_id: str) -> list[dict]:
        return []

    async def get_attachments(self, page_id: str) -> list[dict]:
        return []

    async def get_children(self, page_id: str) -> list[dict]:
        return []

    async def get_links(self, page_id: str) -> list[str]:
        return []

    async def list_changed_pages(self, since: datetime) -> list[str]:
        return ["Space.Home", "Space.Architecture"]


class TestXWikiDocumentationAdapter(DocumentationPortContract):
    @pytest.fixture
    def documentation_provider(self) -> str:
        return "xwiki"

    @pytest.fixture
    def documentation(self) -> DocumentationPort:
        return XWikiDocumentationAdapter(transport=_FakeXWiki(), wiki="test")


async def test_xwiki_fetch_page_version() -> None:
    from brain.domain.external_reference import ExternalReference

    adapter = XWikiDocumentationAdapter(transport=_FakeXWiki(), wiki="test")
    ref = ExternalReference(provider="xwiki", external_id="Space.Home")
    artifact = await adapter.fetch_page_version(ref, "3")
    assert artifact.revision == "3"
    assert artifact.provider == "xwiki"
