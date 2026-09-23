"""XWiki 2.x syntax parser (Step 2).

XWiki REST returns page content in its native ``xwiki/2.1`` syntax (verified:
``?media=converted`` still returns source syntax, and the render endpoint
requires a CSRF token), so no server-side HTML conversion is reliably
available.  This parser normalizes the MVP subset of XWiki 2.x syntax into the
canonical :class:`ParsedDocument` structure:

- headings ``= h1 =`` ... ``====== h6 =======`` -> section nodes with paths;
- bold ``**x**``, italic ``//x//``, underlined ``__x__``, monospace ``##x##``;
- bullet ``*`` / numbered ``#`` / definition ``; term : def`` lists;
- links ``[[page]]`` / ``[[label|page]]`` -> node links;
- code blocks ``{{code language="py"}}...{{/code}}`` -> code-block nodes;
- tables ``| a | b |`` -> table nodes;
- macros ``{{...}}`` are stripped without expansion (MVP);
- everything else groups into paragraph nodes.

Inline formatting markers are stripped from content; links are preserved.
"""

from __future__ import annotations

import re

from brain.domain.documents import DocumentNodeType, DocumentType, SourceArtifact
from brain.domain.parsing import ParsedCodeBlock, ParsedDocument, ParsedNode, ParsedTable

_HEADING_RE = re.compile(r"^(={1,6})\s*(.*?)\s*\1$")
_LIST_BULLET_RE = re.compile(r"^\s*\*\s+(.*)$")
_LIST_NUMBER_RE = re.compile(r"^\s*#\s+(.*)$")
_DEFINITION_RE = re.compile(r"^\s*;\s*(.*?)\s*:\s*(.*)$")
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_CODE_START_RE = re.compile(r'^\{\{code(?:\s+language="?([^"\s}]+)"?)?.*\}\}\s*$')
_CODE_END_RE = re.compile(r"^\{\{/code\}\}\s*$")
_MACRO_BLOCK_RE = re.compile(r"\{\{([^}\n]*)\}\}")
_INLINE_STYLES = [
    (r"\*\*(.+?)\*\*", r"\1"),  # bold
    (r"//(.+?)//", r"\1"),  # italic
    (r"__(.+?)__", r"\1"),  # underline
    (r"##(.+?)##", r"\1"),  # monospace
    (r"~~(.+?)~~", r"\1"),  # strikethrough
]
_LINK_RE = re.compile(r"\[\[([^\]|>]+?)(?:(?:\|)|(?:>>))([^\]]+?)?\]\]")


def _decode(artifact: SourceArtifact) -> str:
    if artifact.content is not None:
        return artifact.content.decode("utf-8", errors="replace")
    if artifact.raw_bytes_ref:
        if artifact.raw_bytes_ref.startswith("data:"):
            import base64

            _, _, payload = artifact.raw_bytes_ref.partition(",")
            return base64.b64decode(payload).decode("utf-8", errors="replace")
        return artifact.raw_bytes_ref
    raise ValueError("SourceArtifact must carry content or a raw bytes reference to be parsed")


def _strip_inline(text: str) -> tuple[str, list[str]]:
    """Strip inline formatting markers and extract links."""
    links: list[str] = []

    def _link_repl(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        label = match.group(2) or target
        links.append(target)
        return label.strip()

    text = _LINK_RE.sub(_link_repl, text)
    for pattern, replacement in _INLINE_STYLES:
        text = re.sub(pattern, replacement, text)
    return text.strip(), links


def _split_table_row(line: str) -> list[str]:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return [c for c in cells if c]


class _Builder:
    """Builds the canonical node tree with a heading stack."""

    def __init__(self) -> None:
        self.nodes: list[ParsedNode] = []
        self._stack: list[ParsedNode] = []
        self._current_content: list[str] = []
        self._current_links: list[str] = []
        self._order = 0

    def _parent(self) -> ParsedNode | None:
        return self._stack[-1] if self._stack else None

    def _attach(self, node: ParsedNode) -> None:
        node.order = self._order
        self._order += 1
        parent = self._parent()
        if parent is None:
            self.nodes.append(node)
        else:
            node.parent_id = parent.id
            parent.child_ids.append(node.id)
            self.nodes.append(node)

    def _flush_content(self) -> None:
        content = "\n".join(self._current_content).strip()
        links = list(self._current_links)
        self._current_content = []
        self._current_links = []
        if content:
            parent = self._parent()
            self._attach(
                ParsedNode(
                    node_type=DocumentNodeType.PARAGRAPH,
                    content=content,
                    links=links,
                    heading_path=list(parent.heading_path) if parent else [],
                )
            )

    def heading(self, level: int, text: str, links: list[str]) -> None:
        self._flush_content()
        while self._stack and len(self._stack) >= level:
            self._stack.pop()
        parent = self._parent()
        heading_path = [*(parent.heading_path if parent else []), text]
        node = ParsedNode(
            node_type=DocumentNodeType.SECTION,
            title=text,
            heading_path=heading_path,
            links=links,
        )
        self._attach(node)
        while len(self._stack) < level:
            self._stack.append(node)

    def paragraph(self, text: str, links: list[str]) -> None:
        if text.strip():
            self._current_content.append(text.strip())
            self._current_links.extend(links)

    def code_block(self, language: str | None, content: str) -> None:
        self._flush_content()
        parent = self._parent()
        self._attach(
            ParsedNode(
                node_type=DocumentNodeType.CODE_BLOCK,
                code_blocks=[ParsedCodeBlock(language=language, content=content)],
                content=content,
                heading_path=list(parent.heading_path) if parent else [],
            )
        )

    def table(self, table: ParsedTable) -> None:
        self._flush_content()
        parent = self._parent()
        rows = "\n".join(
            ["| " + " | ".join(table.headers) + " |"]
            + ["| " + " | ".join(row) + " |" for row in table.rows]
        )
        self._attach(
            ParsedNode(
                node_type=DocumentNodeType.TABLE,
                tables=[table],
                content=rows,
                heading_path=list(parent.heading_path) if parent else [],
            )
        )

    def add_list(self, content: str) -> None:
        parent = self._parent()
        self._attach(
            ParsedNode(
                node_type=DocumentNodeType.LIST,
                content=content,
                heading_path=list(parent.heading_path) if parent else [],
            )
        )

    def finish(self) -> list[ParsedNode]:
        self._flush_content()
        return self.nodes


def _derive_title(body: str) -> str | None:
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            return match.group(2).strip()
    return None


class XWikiSyntaxParser:
    """Parses XWiki 2.x syntax artifacts into a :class:`ParsedDocument`."""

    name = "xwiki"

    _MIME_TYPES = {"text/x-xwiki", "application/x-xwiki"}

    def can_parse(self, artifact: SourceArtifact) -> bool:
        if artifact.mime_type and artifact.mime_type in self._MIME_TYPES:
            return True
        syntax = artifact.metadata.get("syntax") or artifact.metadata.get("xwiki_syntax")
        if syntax and str(syntax).startswith("xwiki/"):
            return True
        name = (artifact.file_name or artifact.source_uri or "").lower()
        return name.endswith(".xwiki")

    def parse(self, artifact: SourceArtifact) -> ParsedDocument:
        text = _decode(artifact)
        builder = _Builder()
        title = _derive_title(text)

        list_buffer: list[str] = []
        table_rows: list[list[str]] = []
        in_code: str | None = None
        code_lines: list[str] = []
        code_language: str | None = None

        def flush_list() -> None:
            if list_buffer:
                builder.add_list("\n".join(list_buffer))
                list_buffer.clear()

        def flush_table() -> None:
            if len(table_rows) >= 2:
                builder.table(ParsedTable(headers=table_rows[0], rows=table_rows[1:]))
            table_rows.clear()

        for line in text.splitlines():
            if in_code is not None:
                if _CODE_END_RE.match(line):
                    builder.code_block(code_language, "\n".join(code_lines))
                    in_code = None
                    code_lines = []
                    code_language = None
                else:
                    code_lines.append(line)
                continue
            code_start = _CODE_START_RE.match(line)
            if code_start:
                flush_list()
                flush_table()
                in_code = "code"
                code_language = code_start.group(1)
                continue
            if _MACRO_BLOCK_RE.match(line):
                flush_list()
                flush_table()
                continue  # macros are stripped in the MVP

            heading = _HEADING_RE.match(line)
            if heading:
                flush_list()
                flush_table()
                text_clean, links = _strip_inline(heading.group(2))
                builder.heading(len(heading.group(1)), text_clean, links)
                continue
            if _TABLE_LINE_RE.match(line):
                flush_list()
                table_rows.append(_split_table_row(line))
                continue
            bullet = _LIST_BULLET_RE.match(line)
            if bullet:
                flush_table()
                item, _ = _strip_inline(bullet.group(1))
                list_buffer.append(f"* {item}")
                continue
            numbered = _LIST_NUMBER_RE.match(line)
            if numbered:
                flush_table()
                item, _ = _strip_inline(numbered.group(1))
                list_buffer.append(f"# {item}")
                continue
            definition = _DEFINITION_RE.match(line)
            if definition:
                flush_table()
                term, _ = _strip_inline(definition.group(1))
                definition_text, _ = _strip_inline(definition.group(2))
                list_buffer.append(f"; {term}: {definition_text}")
                continue
            if not line.strip():
                flush_list()
                flush_table()
                builder.paragraph("", [])
                continue

            flush_list()
            flush_table()
            text_clean, links = _strip_inline(line)
            if text_clean:
                builder.paragraph(text_clean, links)

        if in_code is not None:
            builder.code_block(code_language, "\n".join(code_lines))
        flush_list()
        flush_table()

        if title is None:
            last = artifact.source_uri.rstrip("/").split("/")[-1]
            if last and last != "WebHome":
                title = last

        return ParsedDocument(
            source=artifact,
            title=title,
            document_type=DocumentType.GENERAL,
            front_matter={"syntax": str(artifact.metadata.get("syntax") or "xwiki/2.1")},
            nodes=builder.finish(),
        )


__all__ = ["XWikiSyntaxParser"]
