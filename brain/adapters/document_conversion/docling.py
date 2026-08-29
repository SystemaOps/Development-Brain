"""Docling Serve adapter (Phase 33).

HTTP adapter for Docling Serve: converts complex binary documents (PDF, DOCX,
PPTX) into the canonical :class:`ParsedDocument` model.  The rest of the Brain
never depends on Docling's schema; the adapter normalizes its markdown output
into ``ParsedNode`` entries with heading hierarchy.

Native structured formats (Markdown, OpenAPI, YAML, JSON, source code) are
never routed here — they use native parsers (Task 33.3).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from brain.domain.documents import DocumentNodeType, DocumentType, SourceArtifact
from brain.domain.parsing import ParsedDocument, ParsedNode

_CONVERTED_FORMATS = ["pdf", "docx", "pptx"]
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


class DoclingServeAdapter:
    """DocumentConversionPort implementation backed by Docling Serve."""

    def __init__(self, base_url: str, timeout_seconds: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def convert(self, artifact: SourceArtifact) -> ParsedDocument:
        """POST the artifact to Docling Serve and normalize the markdown."""
        payload = {
            "source_uri": artifact.source_uri,
            "content": (artifact.content or b"").decode("utf-8", errors="replace"),
            "mime_type": artifact.mime_type,
            "file_name": artifact.file_name,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/convert",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise DoclingUnavailableError(f"docling serve unreachable: {exc}") from exc

        markdown = str(raw.get("markdown") or raw.get("text") or "")
        nodes = _markdown_to_nodes(markdown)
        return ParsedDocument(
            source=artifact,
            title=_first_heading(markdown),
            document_type=DocumentType.GENERAL,
            nodes=nodes,
        )

    def supported_formats(self) -> list[str]:
        return list(_CONVERTED_FORMATS)

    async def health(self) -> bool:
        try:
            request = urllib.request.Request(f"{self._base_url}/health", method="GET")
            with urllib.request.urlopen(request, timeout=5):  # noqa: S310
                return True
        except (urllib.error.URLError, OSError, ValueError):
            return False


class DoclingUnavailableError(RuntimeError):
    """Raised when Docling Serve cannot be reached or returns an error."""


def _markdown_to_nodes(markdown: str) -> list[ParsedNode]:
    nodes: list[ParsedNode] = []
    path: list[str] = []
    for index, line in enumerate(markdown.splitlines()):
        match = _HEADING_RE.match(line.strip())
        if match:
            level, title = len(match.group(1)), match.group(2).strip()
            path = path[: level - 1] + [title]
            nodes.append(
                ParsedNode(
                    node_type=DocumentNodeType.SECTION,
                    title=title,
                    heading_path=list(path),
                    content=title,
                    order=index,
                )
            )
        elif line.strip():
            nodes.append(
                ParsedNode(
                    node_type=DocumentNodeType.PARAGRAPH,
                    heading_path=list(path),
                    content=line.strip(),
                    order=index,
                )
            )
    return nodes


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            return match.group(2).strip()
    return None


__all__ = [
    "DoclingServeAdapter",
    "DoclingUnavailableError",
    "_markdown_to_nodes",
]
