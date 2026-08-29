"""Phase 5 golden tests and completion gate.

Given a mixed corpus of canonical documentation (README, a requirements doc, an
ADR, a PDF specification and a nested Markdown structure), the ingestion
pipeline produces structured canonical documents: heading hierarchy preserved,
tables/code blocks typed, references extracted with unresolved ones kept
separately, versions hashed, ADRs turned into Decisions, and semantic chunks
generated only after structure exists.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryDocumentRepository,
)
from brain.adapters.parsers.adr import AdrParser
from brain.adapters.parsers.entity import NoopEntityExtractor
from brain.adapters.parsers.html import HtmlParser
from brain.adapters.parsers.markdown import MarkdownParser
from brain.adapters.parsers.pdf import PdfParser
from brain.adapters.parsers.references import ReferenceExtractor
from brain.adapters.parsers.registry import (
    DefaultParserRegistry,
    DefaultParserSelectionPolicy,
)
from brain.application.document_ingestion import DocumentIngestionService
from brain.domain.documents import DocumentNodeType, DocumentType, SourceArtifact
from brain.domain.identity import new_project_id


@pytest.fixture
def service() -> DocumentIngestionService:
    registry = DefaultParserRegistry(selection_policy=DefaultParserSelectionPolicy())
    registry.register(AdrParser(MarkdownParser()))
    registry.register(MarkdownParser())
    registry.register(HtmlParser())
    registry.register(PdfParser())
    return DocumentIngestionService(
        documents=InMemoryDocumentRepository(),
        parser_registry=registry,
        entity_extractor=NoopEntityExtractor(),
        reference_extractor=ReferenceExtractor(),
        decisions=InMemoryDecisionRepository(),
        event_bus=InMemoryEventBus(),
    )


def _md(content: str, name: str, *, revision: str = "rev-1") -> SourceArtifact:
    return SourceArtifact(
        source_uri=name,
        provider="git_markdown",
        file_name=name,
        revision=revision,
        content=content.encode("utf-8"),
    )


def _pdf(name: str) -> SourceArtifact:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = BytesIO()
    writer.write(buf)
    return SourceArtifact(
        source_uri=name,
        provider="upload",
        file_name=name,
        mime_type="application/pdf",
        content=buf.getvalue(),
    )


README = """# Ada Platform

The Ada platform ingests engineering knowledge.

## Modules

| Module | Purpose |
|--------|---------|
| ingestion | parse documents |
| reasoning | answer questions |

## Quick Start

```bash
uv run brain
```

See REQ-201 for the ingestion contract.
"""

REQUIREMENTS = """# Requirements Specification

## Functional

REQ-100 The system MUST support login.
REQ-200 The system MUST record decisions.

## Non-Functional

The system SHALL be observable.
"""


ADR = """# ADR-010 Use PostgreSQL for canonical state

## Status

Accepted

## Context

We need a transactional store.

## Decision

PostgreSQL is the source of truth.

## Consequences

Migrations are required.
"""


async def test_golden_ingests_readme_preserving_structure(
    service: DocumentIngestionService,
) -> None:
    project_id = new_project_id()
    result = await service.ingest(
        _md(README, "README.md"), project_id=project_id, document_type=DocumentType.ARCHITECTURE
    )
    assert result.created_new_version is True
    assert result.document.title == "Ada Platform"

    sections = [n for n in result.nodes if n.node_type == DocumentNodeType.SECTION]
    assert [s.title for s in sections] == ["Ada Platform", "Modules", "Quick Start"]

    table = next(n for n in result.nodes if n.node_type == DocumentNodeType.TABLE)
    assert "| ingestion" in table.content and "| parse documents" in table.content

    code = next(n for n in result.nodes if n.node_type == DocumentNodeType.CODE_BLOCK)
    assert "uv run brain" in code.content

    unresolved = [r.value for r in result.unresolved_references]
    assert "REQ-201" in unresolved
    assert any("REQ-201" in node.unresolved_refs for node in result.nodes)


async def test_golden_ingests_requirements_document(
    service: DocumentIngestionService,
) -> None:
    project_id = new_project_id()
    result = await service.ingest(
        _md(REQUIREMENTS, "docs/requirements.md"),
        project_id=project_id,
        document_type=DocumentType.REQUIREMENTS,
    )
    assert result.document.type == DocumentType.REQUIREMENTS
    unresolved = [r.value for r in result.unresolved_references]
    assert "REQ-100" in unresolved
    assert "REQ-200" in unresolved
    assert result.chunks


async def test_golden_ingests_adr_and_creates_decision(
    service: DocumentIngestionService,
) -> None:
    project_id = new_project_id()
    result = await service.ingest(
        _md(ADR, "decisions/010-postgres.md"),
        project_id=project_id,
    )
    assert len(result.decisions) == 1
    decision = result.decisions[0]
    assert decision.title == "ADR-010 Use PostgreSQL for canonical state"
    assert decision.status.value == "accepted"
    adr_nodes = [
        n
        for n in result.nodes
        if n.node_type
        in {
            DocumentNodeType.ADR_CONTEXT,
            DocumentNodeType.ADR_DECISION,
            DocumentNodeType.ADR_CONSEQUENCES,
        }
    ]
    assert len(adr_nodes) == 3


async def test_golden_ingests_pdf_spec(service: DocumentIngestionService) -> None:
    project_id = new_project_id()
    result = await service.ingest(
        _pdf("specs/interface.pdf"), project_id=project_id, document_type=DocumentType.ARCHITECTURE
    )
    assert result.created_new_version is True
    assert result.document.title == "specs/interface.pdf"
    assert result.version.checksum


async def test_golden_ingests_nested_markdown(service: DocumentIngestionService) -> None:
    project_id = new_project_id()
    nested = """# Outer

## Middle

### Leaf

Deep content here.

## Sibling

Another section.
"""
    result = await service.ingest(
        _md(nested, "docs/nested/guide.md"),
        project_id=project_id,
        document_type=DocumentType.ARCHITECTURE,
    )
    sections = [n for n in result.nodes if n.node_type == DocumentNodeType.SECTION]
    assert [s.title for s in sections] == ["Outer", "Middle", "Leaf", "Sibling"]
    leaf = next(s for s in sections if s.title == "Leaf")
    assert leaf.heading_path == ["Outer", "Middle", "Leaf"]
    sibling = next(s for s in sections if s.title == "Sibling")
    assert sibling.heading_path == ["Outer", "Sibling"]


async def test_golden_unchanged_reingest_is_noop(service: DocumentIngestionService) -> None:
    project_id = new_project_id()
    first = await service.ingest(
        _md(README, "README.md"), project_id=project_id, document_type=DocumentType.ARCHITECTURE
    )
    second = await service.ingest(
        _md(README, "README.md"), project_id=project_id, document_type=DocumentType.ARCHITECTURE
    )
    assert first.created_new_version is True
    assert second.created_new_version is False
    assert second.version.id == first.version.id
