"""Domain unit tests for Document, DocumentVersion, and DocumentNode."""

from __future__ import annotations

from brain.domain.documents import (
    Document,
    DocumentNode,
    DocumentSource,
    DocumentType,
    DocumentVersion,
    SourceArtifact,
)
from brain.domain.projects import Project


def test_document_defaults() -> None:
    project = Project(name="auth")
    document = Document(
        project_id=project.id,
        title="Architecture",
        source=DocumentSource(provider="git_markdown", uri="docs/architecture.md"),
    )
    assert document.type == DocumentType.GENERAL
    assert document.current_version_id is None


def test_document_version_chain() -> None:
    project = Project(name="auth")
    document = Document(
        project_id=project.id,
        title="README",
        source=DocumentSource(provider="git_markdown", uri="README.md"),
    )
    v1 = DocumentVersion(document_id=document.id, checksum="abc", source_version="main@1")
    assert v1.checksum == "abc"
    assert v1.source_version == "main@1"


def test_document_node_tree() -> None:
    project = Project(name="auth")
    document = Document(
        project_id=project.id,
        title="README",
        source=DocumentSource(provider="git_markdown", uri="README.md"),
    )
    version = DocumentVersion(document_id=document.id, checksum="hash")
    root = DocumentNode(version_id=version.id, title="Root", content="intro")
    child = DocumentNode(
        version_id=version.id,
        title="Child",
        heading_path=["Root", "Child"],
        parent_id=root.id,
        content="detail",
        code_refs=["services/auth.py"],
        links=["https://example.com/auth"],
    )
    assert child.heading_path == ["Root", "Child"]
    assert child.parent_id == root.id
    assert child.code_refs == ["services/auth.py"]
    assert child.links == ["https://example.com/auth"]


def test_source_artifact_inputs() -> None:
    artifact = SourceArtifact(
        source_uri="https://wiki/auth",
        provider="xwiki",
        mime_type="text/html",
        revision="v3",
    )
    assert artifact.provider == "xwiki"
    assert artifact.revision == "v3"
    assert artifact.metadata == {}


def test_document_models_serialize() -> None:
    project = Project(name="auth")
    document = Document(
        project_id=project.id,
        title="README",
        source=DocumentSource(provider="git_markdown", uri="README.md"),
    )
    assert Document.model_validate_json(document.model_dump_json()) == document
