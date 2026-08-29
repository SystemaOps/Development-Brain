"""Document conversion routing (Phase 33).

Routes artifacts to the right converter: native structured formats (Markdown,
OpenAPI, YAML, JSON, source code) always use native parsers; only complex
binary formats (PDF, DOCX, PPTX) go through the optional conversion port
(Task 33.3).  When the conversion provider is unavailable, conversion fails
with a clear capability error while native ingestion keeps working
(Task 33.5).
"""

from __future__ import annotations

from brain.adapters.document_conversion.docling import (
    DoclingUnavailableError,
)
from brain.domain.documents import SourceArtifact
from brain.domain.parsing import ParsedDocument
from brain.ports.document_conversion import DocumentConversionPort

# Formats that are parsed natively and never routed to Docling (Task 33.3).
NATIVE_FORMATS = {
    "text/markdown": ("md", "markdown"),
    "application/openapi+json": ("json", "yaml", "yml"),
    "application/json": ("json",),
    "application/x-yaml": ("yaml", "yml"),
    "text/plain": (),
}

_CONVERTED_EXTENSIONS = (".pdf", ".docx", ".pptx")


class DocumentConversionService:
    """Routes artifacts between native parsing and optional conversion."""

    def __init__(
        self,
        converter: DocumentConversionPort | None,
    ) -> None:
        self._converter = converter

    @property
    def converter(self) -> DocumentConversionPort | None:
        return self._converter

    def is_native(self, artifact: SourceArtifact) -> bool:
        """True if the artifact is a native structured format (Task 33.3)."""
        mime = artifact.mime_type or ""
        name = (artifact.file_name or artifact.source_uri).lower()
        if mime in NATIVE_FORMATS:
            return True
        return name.endswith((".md", ".markdown", ".json", ".yaml", ".yml"))

    def requires_conversion(self, artifact: SourceArtifact) -> bool:
        """True if the artifact needs the optional conversion capability."""
        name = (artifact.file_name or artifact.source_uri).lower()
        return name.endswith(_CONVERTED_EXTENSIONS)

    async def convert(self, artifact: SourceArtifact) -> ParsedDocument:
        """Convert a non-native artifact; raise a clear capability error if
        the provider is unavailable (Task 33.5)."""
        if self.is_native(artifact):
            raise ConversionError(
                f"{artifact.source_uri} is a native structured format and "
                "must be parsed natively, not converted"
            )
        if self._converter is None:
            raise ConversionError(
                "document conversion is not configured; formats "
                + ", ".join(_CONVERTED_EXTENSIONS)
                + " require the conversion capability"
            )
        try:
            return await self._converter.convert(artifact)
        except DoclingUnavailableError as exc:
            raise ConversionError(f"document conversion unavailable: {exc}") from exc

    async def health(self) -> bool:
        if self._converter is None:
            return False
        return await self._converter.health()


class ConversionError(RuntimeError):
    """Raised when document conversion cannot serve a request."""


__all__ = [
    "ConversionError",
    "DocumentConversionService",
    "NATIVE_FORMATS",
]
