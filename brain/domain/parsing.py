"""Canonical parsing models for document ingestion.

:class:`SourceArtifact` is the canonical input (already defined in
``brain.domain.documents``).  Parsers normalize a ``SourceArtifact`` into a
:class:`ParsedDocument` -- a structured, provider-agnostic intermediate model
that preserves heading hierarchy, code blocks, tables, links, and extracted
references -- before the ingestion service persists ``DocumentVersion`` /
``DocumentNode`` rows.

References are extracted deterministically (REQ-xxx, TASK-xxx, ADR-xxx, file
paths, symbols, URLs); references that cannot be resolved against known
identifiers are kept in :attr:`ParsedDocument.unresolved_references` so later
phases (graph, semantic index) can resolve them.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.documents import DocumentNodeType, DocumentType, SourceArtifact


class ReferenceKind(StrEnum):
    REQUIREMENT = "requirement"
    WORK_ITEM = "work_item"
    ADR = "adr"
    FILE_PATH = "file_path"
    SYMBOL = "symbol"
    URL = "url"


class ExtractedReference(BaseModel):
    kind: ReferenceKind
    value: str
    raw: str
    resolved: bool = False


class ParsedTable(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class ParsedCodeBlock(BaseModel):
    language: str | None = None
    content: str = ""


class ParsedNode(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    node_type: DocumentNodeType = DocumentNodeType.SECTION
    title: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    content: str = ""
    parent_id: uuid.UUID | None = None
    child_ids: list[uuid.UUID] = Field(default_factory=list)
    code_blocks: list[ParsedCodeBlock] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    references: list[ExtractedReference] = Field(default_factory=list)
    order: int = 0


class ParsedDocument(BaseModel):
    source: SourceArtifact
    title: str | None = None
    document_type: DocumentType = DocumentType.GENERAL
    front_matter: dict[str, object] = Field(default_factory=dict)
    nodes: list[ParsedNode] = Field(default_factory=list)
    unresolved_references: list[ExtractedReference] = Field(default_factory=list)
    adr_sections: AdrSections | None = None


class AdrSections(BaseModel):
    """Standard ADR sections extracted from a parsed document."""

    context: str = ""
    decision: str = ""
    alternatives: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    status: str | None = None


class CandidateRequirement(BaseModel):
    """Candidate requirement produced by an entity extractor (Task 5.7)."""

    title: str
    description: str = ""
    source_uri: str = ""
    confidence: float = 0.0


class SemanticChunk(BaseModel):
    """A chunk derived only after document structure exists (Task 5.10)."""

    chunk_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    document_id: uuid.UUID
    version_id: uuid.UUID
    node_id: uuid.UUID | None = None
    heading_path: list[str] = Field(default_factory=list)
    content: str = ""
    project_id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None
    commit_sha: str | None = None
    document_type: DocumentType = DocumentType.GENERAL
    chunk_index: int = 0


__all__ = [
    "AdrSections",
    "CandidateRequirement",
    "ExtractedReference",
    "ParsedCodeBlock",
    "ParsedDocument",
    "ParsedNode",
    "ParsedTable",
    "ReferenceKind",
    "SemanticChunk",
]
