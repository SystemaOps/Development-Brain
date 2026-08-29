"""Document conversion port (Phase 33).

An optional replaceable capability for layout-aware document conversion
(complex PDFs, DOCX, PPTX).  Native structured formats (Markdown, OpenAPI,
YAML, JSON, source code) are parsed natively and must never route through a
conversion service (Task 33.3).

``DocumentConversionPort`` is deliberately separate from the ``DocumentParser``
pipeline: conversion produces a normalized :class:`ParsedDocument` that the
existing ingestion pipeline can consume.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.documents import SourceArtifact
from brain.domain.parsing import ParsedDocument


@runtime_checkable
class DocumentConversionPort(Protocol):
    """Converts binary/complex documents into a canonical parsed document."""

    async def convert(self, artifact: SourceArtifact) -> ParsedDocument: ...

    def supported_formats(self) -> list[str]: ...

    async def health(self) -> bool: ...


__all__ = ["DocumentConversionPort"]
