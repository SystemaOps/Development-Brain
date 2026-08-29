"""PDF parser (Task 5.5).

A Docling-equivalent parser behind the :class:`~brain.ports.parsing.DocumentParser`
port.  Uses ``pypdf`` to extract text from PDFs and normalize the pages into
paragraph / section nodes.  A heavier Docling-backed parser (DOCX/PPTX,
layout-aware extraction) can be added behind the same port without changing
the pipeline.
"""

from __future__ import annotations

from io import BytesIO

from brain.domain.documents import DocumentNodeType, SourceArtifact
from brain.domain.parsing import ParsedDocument, ParsedNode

_PDF_MIME = {"application/pdf"}
_PDF_EXT = (".pdf",)


class PdfParser:
    """Parses text-based PDF artifacts into a :class:`ParsedDocument`."""

    name = "pdf"

    def can_parse(self, artifact: SourceArtifact) -> bool:
        name = (artifact.file_name or artifact.source_uri).lower()
        if artifact.mime_type and artifact.mime_type in _PDF_MIME:
            return True
        return name.endswith(_PDF_EXT)

    def parse(self, artifact: SourceArtifact) -> ParsedDocument:
        from pypdf import PdfReader

        content = artifact.content or b""
        reader = PdfReader(BytesIO(content))
        paragraphs = _split_paragraphs(_join_pages(reader))

        nodes: list[ParsedNode] = []
        for index, text in enumerate(paragraphs):
            if _looks_like_heading(text):
                nodes.append(
                    ParsedNode(
                        node_type=DocumentNodeType.SECTION,
                        title=text,
                        heading_path=[text],
                        content=text,
                        order=index,
                    )
                )
            else:
                nodes.append(
                    ParsedNode(
                        node_type=DocumentNodeType.PARAGRAPH,
                        content=text,
                        heading_path=[],
                        order=index,
                    )
                )
        return ParsedDocument(source=artifact, nodes=nodes)


def _join_pages(reader: object) -> str:
    parts = []
    for page in reader.pages:  # type: ignore[attr-defined]
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _looks_like_heading(text: str) -> bool:
    return len(text) < 120 and (text.isupper() or text.rstrip().endswith(":"))


__all__ = ["PdfParser"]
