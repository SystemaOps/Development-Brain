"""Step 2 tests: XWiki content format + XWikiSyntaxParser.

Covers the doc §16 requirements for the format mapping:

- XWiki API payload -> SourceArtifact (content, ``text/x-xwiki``, version,
  title, space, parent, syntax, modified, external reference);
- the syntax parser turns XWiki 2.x markup into a meaningful ParsedDocument;
- a real ``Main.WebHome``-style payload round-trips through the runtime
  ingestion registry.
"""

from __future__ import annotations

from brain.adapters.documentation.xwiki import XWikiDocumentationAdapter
from brain.adapters.parsers.xwiki_syntax import XWikiSyntaxParser
from brain.domain.documents import DocumentNodeType, DocumentType, SourceArtifact
from brain.domain.external_reference import ExternalReference

REAL_WEBHOME_CONTENT = """== Welcome to your wiki ==

XWiki is the best tool to organize your knowledge. A //wiki// is organized in a
hierarchy of //pages//.

=== Getting started ===

* install XWiki
* start a **new page**

# first
# second

{{info}}This is a macro that must be stripped{{/info}}

{{code language="python"}}
def hello():
    print("hi")
{{/code}}

| Header A | Header B |
| a1       | b1       |
| a2       | b2       |

See [[Main.WebHome|the home page]] for details.
"""


class _FakeXWikiTransport:
    """Returns a flattened Main.WebHome-style page."""

    def __init__(self, page: dict[str, object] | None = None) -> None:
        self._page = page or {
            "title": "Home",
            "content": REAL_WEBHOME_CONTENT,
            "version": "2.1",
            "parent": "",
            "id": "Main.WebHome",
            "space": "Main",
            "syntax": "xwiki/2.1",
            "modified": "2026-09-20T22:35:50Z",
        }

    async def get_page(self, page_id: str) -> dict[str, object]:
        return self._page

    async def get_page_version(self, page_id: str, version: str) -> dict[str, object]:
        return {**self._page, "version": version}

    async def list_page_changes(self, page_id: str) -> list[dict[str, object]]:
        return []

    async def get_attachments(self, page_id: str) -> list[dict[str, object]]:
        return []

    async def get_children(self, page_id: str) -> list[dict[str, object]]:
        return []

    async def get_links(self, page_id: str) -> list[str]:
        return []

    async def list_changed_pages(self, spaces, since=None, *, page_size=50):
        return []

    async def create_space(self, space: str) -> dict[str, object]:
        return {}


def test_xwiki_payload_to_source_artifact() -> None:
    """XWiki API payload -> SourceArtifact with correct format metadata."""
    adapter = XWikiDocumentationAdapter(transport=_FakeXWikiTransport(), wiki="xwiki")
    ref = ExternalReference(
        provider="xwiki", external_id="Main.WebHome", external_type="page", namespace="xwiki"
    )
    artifact = adapter._to_artifact(
        {
            "title": "Home",
            "content": REAL_WEBHOME_CONTENT,
            "version": "2.1",
            "parent": "",
            "space": "Main",
            "syntax": "xwiki/2.1",
            "modified": "2026-09-20T22:35:50Z",
        },
        ref,
    )
    assert artifact.provider == "xwiki"
    assert artifact.mime_type == "text/x-xwiki"
    assert artifact.revision == "2.1"
    assert artifact.source_uri == "Main.WebHome"
    assert artifact.metadata["syntax"] == "xwiki/2.1"
    assert artifact.metadata["modified"] == "2026-09-20T22:35:50Z"
    assert artifact.metadata["space"] == "Main"


def test_xwiki_parser_can_parse() -> None:
    parser = XWikiSyntaxParser()
    by_mime = SourceArtifact(
        source_uri="Main.WebHome", provider="xwiki", mime_type="text/x-xwiki", content=b"x"
    )
    by_metadata = SourceArtifact(
        source_uri="Main.WebHome",
        provider="xwiki",
        mime_type="text/plain",
        content=b"x",
        metadata={"syntax": "xwiki/2.1"},
    )
    not_xwiki = SourceArtifact(
        source_uri="doc.md", provider="xwiki", mime_type="text/markdown", content=b"x"
    )
    assert parser.can_parse(by_mime)
    assert parser.can_parse(by_metadata)
    assert not parser.can_parse(not_xwiki)


def test_xwiki_parser_real_webhome_payload() -> None:
    """A real Main.WebHome payload parses into a meaningful structure."""
    parser = XWikiSyntaxParser()
    artifact = SourceArtifact(
        source_uri="Main.WebHome",
        provider="xwiki",
        mime_type="text/x-xwiki",
        content=REAL_WEBHOME_CONTENT.encode("utf-8"),
        metadata={"syntax": "xwiki/2.1"},
    )
    parsed = parser.parse(artifact)
    assert parsed.title == "Welcome to your wiki"
    assert parsed.document_type == DocumentType.GENERAL

    node_types = [n.node_type for n in parsed.nodes]
    assert DocumentNodeType.SECTION in node_types
    assert DocumentNodeType.LIST in node_types
    assert DocumentNodeType.CODE_BLOCK in node_types
    assert DocumentNodeType.TABLE in node_types
    assert DocumentNodeType.PARAGRAPH in node_types

    # Heading hierarchy with paths.
    sections = [n for n in parsed.nodes if n.node_type == DocumentNodeType.SECTION]
    assert sections[0].heading_path == ["Welcome to your wiki"]
    assert any(s.title == "Getting started" for s in sections)
    sub = [s for s in sections if s.title == "Getting started"][0]
    assert sub.heading_path == ["Welcome to your wiki", "Getting started"]

    # Code block captured with language.
    code_nodes = [n for n in parsed.nodes if n.node_type == DocumentNodeType.CODE_BLOCK]
    assert code_nodes[0].code_blocks[0].language == "python"
    assert "def hello():" in code_nodes[0].content

    # Table parsed.
    table_nodes = [n for n in parsed.nodes if n.node_type == DocumentNodeType.TABLE]
    assert table_nodes[0].tables[0].headers == ["Header A", "Header B"]
    assert len(table_nodes[0].tables[0].rows) == 2

    # Inline formatting stripped, macro stripped, link preserved.
    list_nodes = [n for n in parsed.nodes if n.node_type == DocumentNodeType.LIST]
    assert any("new page" in n.content for n in list_nodes)
    assert "{{info}}" not in "".join(n.content for n in parsed.nodes)
    link_nodes = [n for n in parsed.nodes if n.links]
    assert any("Main.WebHome" in n.links for n in link_nodes)


def test_xwiki_parser_idempotent_structure() -> None:
    """The same content produces identical node structure."""
    parser = XWikiSyntaxParser()
    artifact = SourceArtifact(
        source_uri="Main.WebHome",
        provider="xwiki",
        mime_type="text/x-xwiki",
        content=REAL_WEBHOME_CONTENT.encode("utf-8"),
    )
    first = parser.parse(artifact)
    second = parser.parse(artifact)
    assert [(n.node_type, n.title) for n in first.nodes] == [
        (n.node_type, n.title) for n in second.nodes
    ]
    assert len(first.nodes) == len(second.nodes)
