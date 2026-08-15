"""HTML parser (Task 5.4).

Uses BeautifulSoup to parse HTML and rebuild a semantic heading hierarchy
while dropping navigation/header/footer/sidebar noise so engineering content
is not flattened with chrome.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from brain.domain.documents import DocumentNodeType, SourceArtifact
from brain.domain.parsing import ParsedCodeBlock, ParsedDocument, ParsedNode, ParsedTable

_NOISE_SELECTORS = [
    "nav",
    "header",
    "footer",
    "aside",
    "script",
    "style",
    "form",
    "noscript",
    "iframe",
    ".nav",
    ".navbar",
    ".navigation",
    ".breadcrumb",
    ".sidebar",
    ".footer",
    ".header",
    "[role='navigation']",
]


class HtmlParser:
    """Parses HTML artifacts into a :class:`ParsedDocument`."""

    name = "html"

    _MIME_TYPES = {"text/html", "application/xhtml+xml"}
    _EXTENSIONS = {".html", ".htm", ".xhtml"}

    def can_parse(self, artifact: SourceArtifact) -> bool:
        name = (artifact.file_name or artifact.source_uri).lower()
        if artifact.mime_type and artifact.mime_type in self._MIME_TYPES:
            return True
        return any(name.endswith(ext) for ext in self._EXTENSIONS)

    def parse(self, artifact: SourceArtifact) -> ParsedDocument:
        text = _decode(artifact)
        soup = BeautifulSoup(text, "html.parser")
        for selector in _NOISE_SELECTORS:
            for node in soup.select(selector):
                node.decompose()

        title = _page_title(soup)
        body = soup.body or soup
        nodes: list[ParsedNode] = []
        _walk(body, [], nodes)

        return ParsedDocument(source=artifact, title=title, nodes=nodes)


def _walk(
    element: Tag | NavigableString,
    heading_path: list[str],
    nodes: list[ParsedNode],
    *,
    order: int = 0,
) -> None:
    if isinstance(element, NavigableString):
        return
    for child in element.children:
        if not isinstance(child, Tag):
            continue
        tag = child.name or ""
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            while len(heading_path) >= level:
                heading_path.pop()
            heading_path.append(child.get_text(" ", strip=True))
            nodes.append(
                ParsedNode(
                    node_type=DocumentNodeType.SECTION,
                    title=heading_path[-1],
                    heading_path=list(heading_path),
                    order=order,
                )
            )
            order += 1
        elif tag == "table":
            table = _table_from_element(child)
            nodes.append(
                ParsedNode(
                    node_type=DocumentNodeType.TABLE,
                    tables=[table],
                    content=_render_table(table),
                    heading_path=list(heading_path),
                    order=order,
                )
            )
            order += 1
        elif tag == "pre":
            nodes.append(
                ParsedNode(
                    node_type=DocumentNodeType.CODE_BLOCK,
                    code_blocks=[ParsedCodeBlock(content=_text_content(child))],
                    content=_text_content(child),
                    heading_path=list(heading_path),
                    order=order,
                )
            )
            order += 1
        elif tag in {"ul", "ol"}:
            items = [li.get_text(" ", strip=True) for li in child.find_all("li", recursive=False)]
            nodes.append(
                ParsedNode(
                    node_type=DocumentNodeType.LIST,
                    content="\n".join(f"- {item}" for item in items if item),
                    heading_path=list(heading_path),
                    order=order,
                )
            )
            order += 1
        elif tag in {"p", "div", "section", "article", "main", "blockquote"}:
            text = child.get_text("\n", strip=True)
            if text:
                nodes.append(
                    ParsedNode(
                        node_type=DocumentNodeType.PARAGRAPH,
                        content=text,
                        heading_path=list(heading_path),
                        links=_links_from_element(child),
                        order=order,
                    )
                )
                order += 1
            elif tag in {"div", "section", "article", "main"}:
                _walk(child, heading_path, nodes, order=order)


def _table_from_element(element: Tag) -> ParsedTable:
    rows: list[list[str]] = []
    for tr in element.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ParsedTable()
    return ParsedTable(headers=rows[0], rows=rows[1:])


def _render_table(table: ParsedTable) -> str:
    rows = ["| " + " | ".join(table.headers) + " |"]
    rows += ["| " + " | ".join(row) + " |" for row in table.rows]
    return "\n".join(rows)


def _links_from_element(element: Tag) -> list[str]:
    links: list[str] = []
    for a in element.find_all("a", href=True):
        href = a["href"]
        if isinstance(href, str) and href not in links:
            links.append(href)
    return links


def _text_content(element: Tag) -> str:
    return element.get_text("\n", strip=True)


def _page_title(soup: BeautifulSoup) -> str | None:
    title = soup.find("title")
    if title:
        return title.get_text(" ", strip=True)
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else None


def _decode(artifact: SourceArtifact) -> str:
    if artifact.content is not None:
        return artifact.content.decode("utf-8", errors="replace")
    if artifact.raw_bytes_ref:
        return artifact.raw_bytes_ref
    raise ValueError("SourceArtifact must carry content or a raw bytes reference to be parsed")


__all__ = ["HtmlParser", "_NOISE_SELECTORS"]
