"""Document parsing ports.

The ingestion pipeline depends on these interfaces; concrete parsers
(Markdown, HTML, PDF/Docling, ADR) live in ``brain.adapters.parsers`` and are
selected through :class:`ParserRegistry` + :class:`ParserSelectionPolicy`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from brain.domain.documents import SourceArtifact
from brain.domain.parsing import (
    CandidateRequirement,
    ExtractedReference,
    ParsedDocument,
    ParsedNode,
)


@runtime_checkable
class DocumentParser(Protocol):
    """Parses one kind of source artifact into a structured document."""

    @property
    def name(self) -> str: ...

    def can_parse(self, artifact: SourceArtifact) -> bool: ...

    def parse(self, artifact: SourceArtifact) -> ParsedDocument: ...


@runtime_checkable
class ReferenceExtractor(Protocol):
    """Extracts deterministic engineering references from a parsed node (Task 5.8).

    The default adapter uses regular expressions; an LLM-backed extractor can be
    plugged in later without changing the pipeline.
    """

    def extract(self, node: ParsedNode) -> list[ExtractedReference]: ...


@runtime_checkable
class ParserSelectionPolicy(Protocol):
    """Selects the best parser for a source artifact."""

    def select(
        self, parsers: Sequence[DocumentParser], artifact: SourceArtifact
    ) -> DocumentParser | None: ...


@runtime_checkable
class ParserRegistry(Protocol):
    """Knows all registered parsers and picks one for an artifact."""

    def register(self, parser: DocumentParser) -> None: ...

    def select(self, artifact: SourceArtifact) -> DocumentParser | None: ...

    def list(self) -> list[DocumentParser]: ...


@runtime_checkable
class EntityExtractor(Protocol):
    """Pipeline extension point (Task 5.7): parsed document -> candidates.

    The default implementation returns no candidates; an LLM-backed extractor
    can be plugged in later without changing the pipeline.
    """

    def extract(self, parsed: ParsedDocument) -> list[CandidateRequirement]: ...


__all__ = [
    "DocumentParser",
    "EntityExtractor",
    "ParserRegistry",
    "ParserSelectionPolicy",
    "ReferenceExtractor",
]
