"""DocumentRepository contract."""

from __future__ import annotations

import pytest

from brain.domain.documents import (
    Document,
    DocumentNode,
    DocumentSource,
    DocumentVersion,
)
from brain.domain.projects import Project
from brain.ports.repositories import DocumentRepository


def _document(project: Project, title: str, **kwargs: object) -> Document:
    source = kwargs.pop("source", DocumentSource(provider="git_markdown", uri=f"{title}.md"))
    return Document(
        project_id=project.id,
        title=title,
        source=source,  # type: ignore[arg-type]
        **kwargs,
    )


class DocumentRepositoryContract:
    @pytest.fixture
    def document_repository(self) -> DocumentRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, document_repository: DocumentRepository) -> None:
        assert isinstance(document_repository, DocumentRepository)

    async def test_document_crud(self, document_repository: DocumentRepository) -> None:
        project = Project(name="auth")
        document = _document(project, "Architecture", type="architecture")
        await document_repository.create(document)
        assert await document_repository.get(document.id) == document

        document.title = "Updated Architecture"
        await document_repository.update(document)
        assert (await document_repository.get(document.id)).title == "Updated Architecture"

        await document_repository.delete(document.id)
        assert await document_repository.get(document.id) is None

    async def test_list_by_project(self, document_repository: DocumentRepository) -> None:
        project_a = Project(name="a")
        project_b = Project(name="b")
        await document_repository.create(_document(project_a, "one"))
        await document_repository.create(_document(project_a, "two"))
        await document_repository.create(_document(project_b, "other"))
        assert len(await document_repository.list_by_project(project_a.id)) == 2
        assert len(await document_repository.list_by_project(project_b.id)) == 1

    async def test_document_versions_preserve_history(
        self, document_repository: DocumentRepository
    ) -> None:
        project = Project(name="auth")
        document = _document(project, "README")
        await document_repository.create(document)

        v1 = DocumentVersion(document_id=document.id, checksum="abc", source_version="v1")
        await document_repository.add_version(v1)
        v2 = DocumentVersion(document_id=document.id, checksum="def", source_version="v2")
        await document_repository.add_version(v2)

        assert (await document_repository.get_version(v1.id)).checksum == "abc"
        versions = await document_repository.list_versions(document.id)
        assert {v.checksum for v in versions} == {"abc", "def"}

    async def test_document_nodes(self, document_repository: DocumentRepository) -> None:
        project = Project(name="auth")
        document = _document(project, "README")
        await document_repository.create(document)
        version = DocumentVersion(document_id=document.id, checksum="hash")
        await document_repository.add_version(version)

        root = DocumentNode(version_id=version.id, title="Root", content="intro")
        await document_repository.add_node(root)
        child = DocumentNode(
            version_id=version.id,
            title="Child",
            heading_path=["Root", "Child"],
            parent_id=root.id,
            content="detail",
        )
        await document_repository.add_node(child)

        nodes = await document_repository.list_nodes(version.id)
        assert {n.id for n in nodes} == {root.id, child.id}
        assert child.heading_path == ["Root", "Child"]

    async def test_find_by_source(self, document_repository: DocumentRepository) -> None:
        project_a = Project(name="a")
        project_b = Project(name="b")
        source = "docs/README.md"
        doc_a = _document(project_a, "README", source=DocumentSource(provider="git", uri=source))
        doc_b = _document(project_b, "README", source=DocumentSource(provider="git", uri=source))
        await document_repository.create(doc_a)
        await document_repository.create(doc_b)

        assert (await document_repository.find_by_source(project_a.id, source)).id == doc_a.id
        assert (await document_repository.find_by_source(project_b.id, source)).id == doc_b.id
        assert await document_repository.find_by_source(project_a.id, "docs/other.md") is None
