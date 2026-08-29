"""Parsing adapters (Phase 5).

Concrete implementations of the :class:`~brain.ports.parsing.DocumentParser`
and :class:`~brain.ports.parsing.ParserRegistry` ports:

- :class:`MarkdownParser`  -- Markdown (markdown-it-py)
- :class:`HtmlParser`      -- HTML (BeautifulSoup)
- :class:`PdfParser`       -- PDF (pypdf; a Docling-equivalent behind the port)
- :class:`AdrParser`       -- ADR detection on top of the Markdown parser
"""

from brain.adapters.parsers.adr import AdrParser
from brain.adapters.parsers.entity import NoopEntityExtractor
from brain.adapters.parsers.html import HtmlParser
from brain.adapters.parsers.markdown import MarkdownParser
from brain.adapters.parsers.pdf import PdfParser
from brain.adapters.parsers.references import ReferenceExtractor
from brain.adapters.parsers.registry import (
    DefaultParserRegistry,
    DefaultParserSelectionPolicy,
)

__all__ = [
    "AdrParser",
    "DefaultParserRegistry",
    "DefaultParserSelectionPolicy",
    "HtmlParser",
    "MarkdownParser",
    "NoopEntityExtractor",
    "PdfParser",
    "ReferenceExtractor",
]
