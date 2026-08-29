"""Document ingestion service tests (Phase 5)."""

from __future__ import annotations

import pytest

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryDocumentRepository,
)
from brain.adapters.parsers.adr import AdrParser
from brain.adapters.parsers.entity import NoopEntityExtractor
from brain.adapters.parsers.markdown import MarkdownParser
from brain.adapters.parsers.references import ReferenceExtractor
from brain.adapters.parsers.registry import (
    DefaultParserRegistry,
    DefaultParserSelectionPolicy,
)
from brain.application.document_ingestion import DocumentIngestionService
from brain.domain.documents import (
    DocumentNodeType,
    DocumentType,
    SourceArtifact,
)
from brain.domain.identity import new_project_id, new_repository_id


@pytest.fixture
def documents() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def decisions() -> InMemoryDecisionRepository:
    return InMemoryDecisionRepository()


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def service(
    documents: InMemoryDocumentRepository,
    decisions: InMemoryDecisionRepository,
    event_bus: InMemoryEventBus,
) -> DocumentIngestionService:
    registry = DefaultParserRegistry(selection_policy=DefaultParserSelectionPolicy())
    registry.register(AdrParser(MarkdownParser()))
    registry.register(MarkdownParser())
    return DocumentIngestionService(
        documents=documents,
        parser_registry=registry,
        entity_extractor=NoopEntityExtractor(),
        reference_extractor=ReferenceExtractor(),
        decisions=decisions,
        event_bus=event_bus,
    )


def _artifact(
    content: str, *, name: str = "docs/readme.md", revision: str = "abc1234"
) -> SourceArtifact:
    return SourceArtifact(
        source_uri=name,
        provider="test",
        file_name=name,
        revision=revision,
        content=content.encode("utf-8"),
    )


DOC = """# Product Requirements

REQ-100 requires a login flow. See [auth](https://example.com/auth).

## Security

TASK-42 covers threat modelling.
"""


async def test_ingest_creates_document_version_nodes_and_chunks(
    service: DocumentIngestionService,
    documents: InMemoryDocumentRepository,
    event_bus: InMemoryEventBus,
) -> None:
    project_id = new_project_id()
    result = await service.ingest(
        _artifact(DOC), project_id=project_id, document_type=DocumentType.REQUIREMENTS
    )

    assert result.created_new_version is True
    assert result.document.type == DocumentType.REQUIREMENTS
    assert result.document.title == "Product Requirements"
    assert result.document.current_version_id == result.version.id
    assert result.version.checksum

    sections = [n for n in result.nodes if n.node_type == DocumentNodeType.SECTION]
    assert [s.title for s in sections] == ["Product Requirements", "Security"]
    assert sections[1].heading_path == ["Product Requirements", "Security"]

    assert result.chunks
    chunk = result.chunks[0]
    assert chunk.document_id == result.document.id
    assert chunk.version_id == result.version.id

    unresolved = [r.value for r in result.unresolved_references]
    assert "REQ-100" in unresolved
    assert "TASK-42" in unresolved

    assert len(event_bus.published) == 1


async def test_ingest_unchanged_content_is_noop(
    service: DocumentIngestionService,
    documents: InMemoryDocumentRepository,
) -> None:
    project_id = new_project_id()
    first = await service.ingest(
        _artifact(DOC), project_id=project_id, document_type=DocumentType.REQUIREMENTS
    )
    second = await service.ingest(
        _artifact(DOC), project_id=project_id, document_type=DocumentType.REQUIREMENTS
    )

    assert second.created_new_version is False
    assert second.version.id == first.version.id
    versions = await documents.list_versions(first.document.id)
    assert len(versions) == 1


async def test_ingest_changed_content_creates_new_version_preserving_old(
    service: DocumentIngestionService,
    documents: InMemoryDocumentRepository,
) -> None:
    project_id = new_project_id()
    first = await service.ingest(
        _artifact(DOC), project_id=project_id, document_type=DocumentType.REQUIREMENTS
    )
    changed = _artifact(DOC + "\n## Added\nNew section here.\n", revision="def5678")
    second = await service.ingest(
        changed, project_id=project_id, document_type=DocumentType.REQUIREMENTS
    )

    assert second.created_new_version is True
    assert second.version.id != first.version.id
    assert second.document.current_version_id == second.version.id
    versions = await documents.list_versions(first.document.id)
    assert len(versions) == 2

    old_nodes = await documents.list_nodes(first.version.id)
    assert any(n.title == "Product Requirements" for n in old_nodes)


ADR = """# ADR-002 Use Event Sourcing

## Status

Accepted

## Context

Domain events need to be stored durably.

## Decision

We adopt event sourcing for the transaction log.

## Consequences

Read models must be rebuilt.
"""


async def test_ingest_adr_creates_decision(
    service: DocumentIngestionService,
    decisions: InMemoryDecisionRepository,
) -> None:
    project_id = new_project_id()
    result = await service.ingest(
        _artifact(ADR, name="decisions/002-event-sourcing.md"),
        project_id=project_id,
    )

    assert len(result.decisions) == 1
    decision = result.decisions[0]
    assert decision.title == "ADR-002 Use Event Sourcing"
    assert "event sourcing" in decision.decision
    assert decision.project_id == project_id
    persisted = await decisions.list_by_project(project_id)
    assert persisted == [decision]


async def test_ingest_plain_text_without_parser_raises(
    service: DocumentIngestionService,
) -> None:
    artifact = SourceArtifact(
        source_uri="notes.txt",
        provider="test",
        file_name="notes.txt",
        mime_type="text/plain",
        content=b"hello",
    )
    with pytest.raises(ValueError, match="no parser registered"):
        await service.ingest(artifact, project_id=new_project_id())


async def test_find_by_source_round_trip(
    service: DocumentIngestionService,
    documents: InMemoryDocumentRepository,
) -> None:
    project_id = new_project_id()
    result = await service.ingest(
        _artifact(DOC), project_id=project_id, document_type=DocumentType.REQUIREMENTS
    )
    found = await documents.find_by_source(project_id, "docs/readme.md")
    assert found is not None
    assert found.id == result.document.id


async def test_ingest_with_repository_metadata(
    service: DocumentIngestionService,
) -> None:
    project_id = new_project_id()
    repository_id = new_repository_id()
    result = await service.ingest(
        _artifact(DOC, revision="sha-01"),
        project_id=project_id,
        document_type=DocumentType.REQUIREMENTS,
        repository_id=repository_id,
        commit_sha="sha-01",
    )
    assert result.version.repository_id == repository_id
    assert result.version.commit_sha == "sha-01"
