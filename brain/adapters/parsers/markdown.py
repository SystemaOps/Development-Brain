"""Markdown parser (Task 5.3).

Uses ``markdown-it-py`` to tokenize the source, then walks the token stream to
rebuild a heading hierarchy with ``DocumentNodeType``-preserving nodes:

- headings          -> SECTION (title + heading_path)
- paragraphs        -> PARAGRAPH
- fenced/indented   -> CODE_BLOCK (language preserved)
- tables            -> TABLE (headers + rows preserved structurally)
- bullet/ordered    -> LIST
- YAML front matter -> FRONT_MATTER (parsed into a dict)

Inline links are collected onto the containing node's ``links`` list.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.token import Token

from brain.domain.documents import DocumentNodeType, SourceArtifact
from brain.domain.parsing import (
    ExtractedReference,
    ParsedCodeBlock,
    ParsedDocument,
    ParsedNode,
    ParsedTable,
)


class _Builder:
    """Builds a ParsedNode tree from a markdown-it token stream."""

    def __init__(self) -> None:
        self.nodes: list[ParsedNode] = []
        self._stack: list[ParsedNode] = []
        self._order = 0
        self._current_content: list[str] = []
        self._current_links: list[str] = []

    def _parent(self) -> ParsedNode:
        return self._stack[-1] if self._stack else None  # type: ignore[return-value]

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
            node = ParsedNode(
                node_type=DocumentNodeType.PARAGRAPH,
                content=content,
                links=links,
                heading_path=list(parent.heading_path) if parent else [],
            )
            self._attach(node)

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
        node = ParsedNode(
            node_type=DocumentNodeType.CODE_BLOCK,
            code_blocks=[ParsedCodeBlock(language=language, content=content)],
            content=content,
            heading_path=list(parent.heading_path) if parent else [],
        )
        self._attach(node)

    def table(self, table: ParsedTable) -> None:
        self._flush_content()
        parent = self._parent()
        rows = "\n".join(
            ["| " + " | ".join(table.headers) + " |"]
            + ["| " + " | ".join(row) + " |" for row in table.rows]
        )
        node = ParsedNode(
            node_type=DocumentNodeType.TABLE,
            tables=[table],
            content=rows,
            heading_path=list(parent.heading_path) if parent else [],
        )
        self._attach(node)

    def add_list(self, content: str) -> None:
        parent = self._parent()
        node = ParsedNode(
            node_type=DocumentNodeType.LIST,
            content=content,
            heading_path=list(parent.heading_path) if parent else [],
        )
        self._attach(node)

    def finish(self, references: list[ExtractedReference] | None = None) -> list[ParsedNode]:
        self._flush_content()
        if references:
            for node in self.nodes:
                node.references = [r for r in references if r.value in node.content]
        return self.nodes


def _inline_text(tokens: list[Token]) -> tuple[str, list[str]]:
    parts: list[str] = []
    links: list[str] = []
    for tok in tokens:
        if tok.type == "text" or tok.type == "code_inline":
            parts.append(str(tok.content))
        elif tok.type == "link_open":
            href = tok.attrGet("href")
            if href:
                links.append(str(href))
        elif tok.type == "softbreak" or tok.type == "hardbreak":
            parts.append("\n")
    return "".join(parts), links


def _table_from_tokens(rows_tokens: list[list[Token]]) -> ParsedTable:
    headers: list[str] = []
    rows: list[list[str]] = []
    for row in rows_tokens:
        cells: list[str] = []
        for tok in row:
            if tok.type == "inline":
                text, _ = _inline_text(tok.children or [])
                cells.append(text)
        if not headers:
            headers = cells
        else:
            rows.append(cells)
    return ParsedTable(headers=headers, rows=rows)


class MarkdownParser:
    """Parses Markdown artifacts into a :class:`ParsedDocument`."""

    name = "markdown"

    _MIME_TYPES = {"text/markdown", "text/x-markdown"}
    _EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}

    def can_parse(self, artifact: SourceArtifact) -> bool:
        name = (artifact.file_name or artifact.source_uri).lower()
        if artifact.mime_type and artifact.mime_type in self._MIME_TYPES:
            return True
        return any(name.endswith(ext) for ext in self._EXTENSIONS)

    def parse(self, artifact: SourceArtifact) -> ParsedDocument:
        text = _decode(artifact)
        front_matter, body = _extract_front_matter(text)
        title = _derive_title(body)

        md = MarkdownIt("commonmark", {"html": True}).enable("table")
        tokens = md.parse(body)

        builder = _Builder()
        list_buffer: list[str] = []

        def flush_list() -> None:
            if list_buffer:
                builder.add_list("\n".join(list_buffer))
                list_buffer.clear()

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == "heading_open":
                level = int(tok.tag[1])
                text, links = _inline_text(tokens[i + 1].children or [])
                builder.heading(level, text, links)
                i += 3
                continue
            if tok.type == "paragraph_open":
                text, links = _inline_text(tokens[i + 1].children or [])
                builder.paragraph(text, links)
                i += 3
                continue
            if tok.type == "fence" or tok.type == "code_block":
                flush_list()
                info = (tok.info or "").strip().split()[0] if tok.type == "fence" else None
                builder.code_block(info or None, tok.content)
                i += 1
                continue
            if tok.type == "table_open":
                flush_list()
                rows_tokens: list[list[Token]] = []
                j = i + 1
                while j < len(tokens) and tokens[j].type != "table_close":
                    if tokens[j].type == "tr_open":
                        cells: list[Token] = []
                        k = j + 1
                        while k < len(tokens) and tokens[k].type != "tr_close":
                            if tokens[k].type in ("th_open", "td_open"):
                                cells.append(tokens[k + 1])
                            k += 1
                        rows_tokens.append(cells)
                        j = k
                    else:
                        j += 1
                builder.table(_table_from_tokens(rows_tokens))
                i = j + 1
                continue
            if tok.type == "bullet_list_open" or tok.type == "ordered_list_open":
                flush_list()
                i += 1
                continue
            if tok.type == "list_item_open":
                inline_tok = None
                for candidate in tokens[i + 1 : i + 4]:
                    if candidate.type == "inline":
                        inline_tok = candidate
                        break
                text, _ = (
                    _inline_text(inline_tok.children or []) if inline_tok is not None else ("", [])
                )
                list_buffer.append("- " + text if text else "-")
                i += 2
                continue
            if tok.type == "list_item_close":
                i += 1
                continue
            if tok.type in ("list_close", "bullet_list_close", "ordered_list_close"):
                flush_list()
                i += 1
                continue
            i += 1

        flush_list()
        nodes = builder.finish()

        # Assign front matter node.
        if front_matter:
            fm_node = ParsedNode(
                node_type=DocumentNodeType.FRONT_MATTER,
                title="Front Matter",
                content=_dump_front_matter(front_matter),
                order=0,
            )
            nodes.insert(0, fm_node)

        return ParsedDocument(
            source=artifact,
            title=title,
            front_matter=front_matter,
            nodes=nodes,
        )


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


def _extract_front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if len(lines) < 3:
        return {}, text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text
    fm: dict[str, object] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fm[key.strip()] = value.strip().strip("\"'")
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return fm, body


def _derive_title(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _dump_front_matter(fm: dict[str, object]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in fm.items())


__all__ = ["MarkdownParser"]
