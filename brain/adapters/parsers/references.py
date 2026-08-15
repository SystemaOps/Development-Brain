"""Deterministic reference extraction (Task 5.8).

Extracts canonical engineering references from parsed node content and links:

- ``REQ-123``          -> requirement
- ``TASK-12``          -> work item
- ``ADR-005``          -> ADR
- ``path/to/file.py``  -> file path
- ``package.Symbol``   -> symbol (camel-case dotted identifier)
- ``https://...``      -> URL

References are stored on the node as :class:`ExtractedReference`.  Those that
cannot be resolved against known identifiers stay unresolved and are collected
separately by the ingestion pipeline.
"""

from __future__ import annotations

import re

from brain.domain.parsing import (
    ExtractedReference,
    ParsedNode,
    ReferenceKind,
)

_REQ_PATTERN = re.compile(r"\b(?:REQ|SR)[-_]?\d{2,}\b")
_TASK_PATTERN = re.compile(r"\b(?:TASK|WI)[-_]?\d{2,}\b")
_ADR_PATTERN = re.compile(r"\bADR[-_]\d{3,}\b")
_URL_PATTERN = re.compile(r"https?://[^\s)\]\"']+")
_FILE_PATTERN = re.compile(
    r"\b(?:[A-Za-z0-9_./-]+/[A-Za-z0-9_.-]+\.(?:py|ts|js|go|rs|java|md|yaml|yml|toml|json))\b"
)
_SYMBOL_PATTERN = re.compile(r"\b(?:[a-z_]\w*\.)+[A-Za-z_]\w*\b")


class ReferenceExtractor:
    """Extracts references from a single parsed node."""

    def extract(self, node: ParsedNode) -> list[ExtractedReference]:
        text = node.content
        references: list[ExtractedReference] = []
        seen: set[tuple[str, str]] = set()

        for pattern, kind in (
            (_REQ_PATTERN, ReferenceKind.REQUIREMENT),
            (_TASK_PATTERN, ReferenceKind.WORK_ITEM),
            (_ADR_PATTERN, ReferenceKind.ADR),
            (_URL_PATTERN, ReferenceKind.URL),
            (_FILE_PATTERN, ReferenceKind.FILE_PATH),
            (_SYMBOL_PATTERN, ReferenceKind.SYMBOL),
        ):
            for match in pattern.finditer(text):
                value = match.group(0).rstrip(".,;:!?")
                if not value:
                    continue
                key = (kind.value, value)
                if key not in seen:
                    seen.add(key)
                    references.append(ExtractedReference(kind=kind, value=value, raw=value))

        for link in node.links:
            if link.startswith(("http://", "https://")):
                key = ("url", link)
                if key not in seen:
                    seen.add(key)
                    references.append(
                        ExtractedReference(kind=ReferenceKind.URL, value=link, raw=link)
                    )

        return references


__all__ = ["ReferenceExtractor"]
