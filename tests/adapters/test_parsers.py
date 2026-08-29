"""Parser tests (Phase 5)."""

from __future__ import annotations

from brain.adapters.parsers.adr import AdrParser
from brain.adapters.parsers.html import HtmlParser
from brain.adapters.parsers.markdown import MarkdownParser
from brain.adapters.parsers.pdf import PdfParser
from brain.adapters.parsers.references import ReferenceExtractor
from brain.adapters.parsers.registry import (
    DefaultParserRegistry,
    DefaultParserSelectionPolicy,
)
from brain.domain.documents import DocumentNodeType, SourceArtifact
from brain.domain.parsing import ParsedNode, ReferenceKind


def _artifact(content: str, *, name: str = "doc.md", mime: str | None = None) -> SourceArtifact:
    return SourceArtifact(
        source_uri=name,
        provider="test",
        file_name=name,
        mime_type=mime,
        content=content.encode("utf-8"),
    )


MARKDOWN_SAMPLE = """---
title: Architecture Overview
status: active
---

# Overview

This is the intro paragraph with a [link](https://example.com/docs) and a REQ-123 reference.

## Components

| Name  | Purpose  |
|-------|----------|
| api   | gateway  |

```python
def handler(event):
    return event
```

- first item
- second item

## Deployment

Deployed to production.
"""


def test_markdown_parser_preserves_hierarchy() -> None:
    parsed = MarkdownParser().parse(_artifact(MARKDOWN_SAMPLE))
    assert parsed.title == "Overview"
    assert parsed.front_matter == {"title": "Architecture Overview", "status": "active"}

    sections = [n for n in parsed.nodes if n.node_type == DocumentNodeType.SECTION]
    assert [s.title for s in sections] == ["Overview", "Components", "Deployment"]
    assert sections[1].heading_path == ["Overview", "Components"]

    table = next(n for n in parsed.nodes if n.node_type == DocumentNodeType.TABLE)
    assert table.tables[0].headers == ["Name", "Purpose"]
    assert table.tables[0].rows == [["api", "gateway"]]

    code = next(n for n in parsed.nodes if n.node_type == DocumentNodeType.CODE_BLOCK)
    assert code.code_blocks[0].language == "python"
    assert "def handler" in code.code_blocks[0].content

    lists = [n for n in parsed.nodes if n.node_type == DocumentNodeType.LIST]
    assert lists and "first item" in lists[0].content


def test_markdown_parser_collects_links() -> None:
    parsed = MarkdownParser().parse(_artifact(MARKDOWN_SAMPLE))
    paragraphs = [n for n in parsed.nodes if n.node_type == DocumentNodeType.PARAGRAPH]
    intro = next(n for n in paragraphs if "intro paragraph" in n.content)
    assert "https://example.com/docs" in intro.links


def test_markdown_parser_front_matter_only() -> None:
    parsed = MarkdownParser().parse(_artifact("---\ntitle: T\n---\n\nBody"))
    assert parsed.front_matter == {"title": "T"}
    types = {n.node_type for n in parsed.nodes}
    assert DocumentNodeType.FRONT_MATTER in types


def test_reference_extractor_finds_all_kinds() -> None:
    node = ParsedNode(
        node_type=DocumentNodeType.PARAGRAPH,
        content=(
            "See REQ-123 and TASK-45 for context. ADR-007 decided it. "
            "Source at src/app.py and url https://example.com/x. "
            "Uses auth.service.Client."
        ),
        links=["https://example.com/y"],
    )
    refs = ReferenceExtractor().extract(node)
    kinds = {r.kind for r in refs}
    assert ReferenceKind.REQUIREMENT in kinds
    assert ReferenceKind.WORK_ITEM in kinds
    assert ReferenceKind.ADR in kinds
    assert ReferenceKind.FILE_PATH in kinds
    assert ReferenceKind.URL in kinds
    assert ReferenceKind.SYMBOL in kinds
    values = [r.value for r in refs]
    assert "REQ-123" in values
    assert "TASK-45" in values
    assert "ADR-007" in values
    assert "https://example.com/x" in values
    assert "https://example.com/y" in values


HTML_SAMPLE = """<!DOCTYPE html>
<html>
<head><title>Service Docs</title></head>
<body>
<nav><a href="/">Home</a></nav>
<header>Site Header</header>
<h1>Payment Service</h1>
<p>Handles payments for the platform.</p>
<h2>Endpoints</h2>
<table>
<tr><th>Method</th><th>Path</th></tr>
<tr><td>POST</td><td>/charge</td></tr>
</table>
<pre><code>def charge():
    pass</code></pre>
<footer>Copyright</footer>
</body>
</html>
"""


def test_html_parser_strips_noise_and_preserves_hierarchy() -> None:
    parsed = HtmlParser().parse(_artifact(HTML_SAMPLE, name="docs.html", mime="text/html"))
    assert parsed.title == "Service Docs"
    sections = [n for n in parsed.nodes if n.node_type == DocumentNodeType.SECTION]
    assert [s.title for s in sections] == ["Payment Service", "Endpoints"]

    paragraphs = [n.content for n in parsed.nodes if n.node_type == DocumentNodeType.PARAGRAPH]
    combined = " ".join(paragraphs)
    assert "Handles payments" in combined
    assert "Site Header" not in combined
    assert "Copyright" not in combined
    assert "Home" not in combined

    table = next(n for n in parsed.nodes if n.node_type == DocumentNodeType.TABLE)
    assert table.tables[0].headers == ["Method", "Path"]
    assert table.tables[0].rows == [["POST", "/charge"]]


def test_pdf_parser_selects_and_parses() -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Spec"})
    buf = BytesIO()
    writer.write(buf)
    artifact = SourceArtifact(
        source_uri="spec.pdf",
        provider="test",
        file_name="spec.pdf",
        mime_type="application/pdf",
        content=buf.getvalue(),
    )
    pdf_parser = PdfParser()
    assert pdf_parser.can_parse(artifact)
    # A blank page has no text; parsing must still yield an empty node list.
    parsed = pdf_parser.parse(artifact)
    assert parsed.source.source_uri == "spec.pdf"


def test_registry_selects_by_mime_and_extension() -> None:
    registry = DefaultParserRegistry(selection_policy=DefaultParserSelectionPolicy())
    registry.register(MarkdownParser())
    registry.register(HtmlParser())
    registry.register(PdfParser())

    md = registry.select(_artifact("# Title", name="README.md"))
    assert md is not None and md.name == "markdown"
    html = registry.select(_artifact("<p>x</p>", name="x.html", mime="text/html"))
    assert html is not None and html.name == "html"
    pdf = registry.select(_artifact("", name="x.pdf", mime="application/pdf"))
    assert pdf is not None and pdf.name == "pdf"
    assert registry.select(_artifact("text", name="notes.txt", mime="text/plain")) is None


ADR_SAMPLE = """# ADR-001 Use PostgreSQL for storage

## Status

Accepted

## Context

We need durable transactional storage for canonical state.

## Decision

We will use PostgreSQL as the transactional source of truth.

## Alternatives

- MySQL
- SQLite

## Consequences

Migration tooling is required.
"""


def test_adr_parser_detects_sections() -> None:
    parser = AdrParser(MarkdownParser())
    parsed = parser.parse(_artifact(ADR_SAMPLE, name="adr/001-use-postgres.md"))
    assert parsed.front_matter.get("adr") is True
    assert parsed.adr_sections is not None
    sections = parsed.adr_sections
    assert sections.status == "Accepted"
    assert "durable transactional storage" in sections.context
    assert "PostgreSQL as the transactional source of truth" in sections.decision
    assert sections.alternatives == ["- MySQL\n- SQLite"]
    assert any("Migration tooling" in c for c in sections.consequences)
    assert parser.status(sections.status) is not None

    node_types = {n.node_type for n in parsed.nodes}
    assert DocumentNodeType.ADR_DECISION in node_types
    assert DocumentNodeType.ADR_CONTEXT in node_types
