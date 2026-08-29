"""Phase 33 golden tests and completion gate.

Document conversion works when Docling is available without making Docling a
core dependency: native structured formats use native parsers, conversion
fails with a clear capability error when disabled, and the Brain stays ready.
"""

from __future__ import annotations

import json
import urllib.request
from unittest.mock import patch

from brain.adapters.document_conversion.docling import (
    DoclingServeAdapter,
    _markdown_to_nodes,
)
from brain.application.document_conversion import (
    ConversionError,
    DocumentConversionService,
)
from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    DocumentConversionSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.documents import DocumentNodeType, SourceArtifact


def _artifact(uri: str = "spec.pdf", mime: str = "application/pdf") -> SourceArtifact:
    return SourceArtifact(
        source_uri=uri,
        provider="api",
        mime_type=mime,
        file_name=uri.split("/")[-1],
        content=b"%PDF-1.4 test",
    )


def test_markdown_to_nodes_preserves_heading_hierarchy() -> None:
    nodes = _markdown_to_nodes("# Overview\nSome text\n## Details\nMore\n\nPlain paragraph")
    sections = [n for n in nodes if n.node_type == DocumentNodeType.SECTION]
    paragraphs = [n for n in nodes if n.node_type == DocumentNodeType.PARAGRAPH]
    assert sections[0].title == "Overview"
    assert sections[0].heading_path == ["Overview"]
    assert sections[1].title == "Details"
    assert sections[1].heading_path == ["Overview", "Details"]
    assert any("Some text" in p.content for p in paragraphs)


def test_native_formats_are_not_routed_to_conversion() -> None:
    service = DocumentConversionService(converter=None)
    for uri, mime in [
        ("README.md", "text/markdown"),
        ("openapi.yaml", "application/x-yaml"),
        ("config.json", "application/json"),
        ("source.py", "text/plain"),
    ]:
        artifact = SourceArtifact(source_uri=uri, provider="api", mime_type=mime, file_name=uri)
        assert service.is_native(artifact), uri


def test_pdf_requires_conversion() -> None:
    service = DocumentConversionService(converter=None)
    assert service.requires_conversion(_artifact())
    assert not service.is_native(_artifact())


def test_conversion_disabled_raises_clear_error() -> None:
    service = DocumentConversionService(converter=None)
    try:
        import asyncio

        asyncio.run(service.convert(_artifact()))
    except ConversionError as exc:
        assert "not configured" in str(exc)
        assert "capability" in str(exc)
    else:
        raise AssertionError("expected ConversionError")


def test_native_artifact_never_converted() -> None:
    service = DocumentConversionService(
        converter=DoclingServeAdapter(base_url="http://localhost:5001")
    )
    markdown_artifact = SourceArtifact(
        source_uri="doc.md", provider="api", mime_type="text/markdown", file_name="doc.md"
    )
    try:
        import asyncio

        asyncio.run(service.convert(markdown_artifact))
    except ConversionError as exc:
        assert "native" in str(exc)
    else:
        raise AssertionError("expected ConversionError for native artifact")


def test_docling_adapter_normalizes_response() -> None:
    fake_response = json.dumps(
        {
            "markdown": "# Conversion Report\nConverted body text.",
        }
    ).encode("utf-8")

    class _FakeResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self._data

    def _fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        del timeout, request
        return _FakeResponse(fake_response)

    adapter = DoclingServeAdapter(base_url="http://docling:5001")
    import asyncio

    with patch.object(urllib.request, "urlopen", _fake_urlopen):
        document = asyncio.run(adapter.convert(_artifact()))
    assert document.title == "Conversion Report"
    sections = [n for n in document.nodes if n.node_type == DocumentNodeType.SECTION]
    assert sections[0].title == "Conversion Report"
    assert any("Converted body text" in n.content for n in document.nodes)


def test_docling_adapter_supported_formats() -> None:
    adapter = DoclingServeAdapter(base_url="http://docling:5001")
    assert adapter.supported_formats() == ["pdf", "docx", "pptx"]


async def test_container_core_only_reports_conversion_disabled() -> None:
    """Brain ready with conversion disabled; native ingestion unaffected."""
    container = await create_brain_container(
        BrainSettings(
            storage_state=PostgresSettings(
                url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
            ),
            storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
            storage_semantic=WeaviateSettings(host="localhost"),
            storage_queue=RedisSettings(url="redis://localhost:6379/0"),
            work_management=WorkManagementSettings(enabled=False),
            documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
            source_control=SourceControlSettings(enabled=False),
            verification=VerificationSettings(require_pass_before_pr=True),
            document_conversion=DocumentConversionSettings(enabled=False),
        )
    )
    try:
        assert container.capabilities()["document_conversion"] == "DISABLED"
        assert container.is_ready() is True
        # Native document ingestion service still available.
        assert container.services["document_ingestion"] is not None
    finally:
        await container.close()


async def test_container_conversion_configured_reports_available() -> None:
    """With a configured base URL the capability is AVAILABLE (if reachable)."""
    container = await create_brain_container(
        BrainSettings(
            storage_state=PostgresSettings(
                url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
            ),
            storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
            storage_semantic=WeaviateSettings(host="localhost"),
            storage_queue=RedisSettings(url="redis://localhost:6379/0"),
            work_management=WorkManagementSettings(enabled=False),
            documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
            source_control=SourceControlSettings(enabled=False),
            verification=VerificationSettings(require_pass_before_pr=True),
            document_conversion=DocumentConversionSettings(
                enabled=True,
                provider="docling_serve",
                base_url="http://docling:5001",
            ),
        )
    )
    try:
        assert container.capabilities()["document_conversion"] == "AVAILABLE"
        assert container.is_ready() is True
        conversion = container.services["document_conversion"]
        assert isinstance(conversion, DocumentConversionService)
        assert conversion.converter is not None
    finally:
        await container.close()
