"""ADR parser (Task 5.6).

Detects Architecture Decision Records and extracts the standard sections --
Status, Context, Decision, Alternatives (or Considered Options), Consequences --
so an ingestion service can create canonical :class:`Decision` entities.
"""

from __future__ import annotations

from brain.domain.decisions import DecisionStatus
from brain.domain.documents import DocumentNodeType, SourceArtifact
from brain.domain.parsing import AdrSections, ParsedDocument, ParsedNode
from brain.ports.parsing import DocumentParser

_SECTION_HEADINGS = {
    "status": "status",
    "context": "context",
    "decision": "decision",
    "alternatives": "alternatives",
    "considered options": "alternatives",
    "consequences": "consequences",
}

_SECTION_NODE_TYPES = {
    "context": DocumentNodeType.ADR_CONTEXT,
    "decision": DocumentNodeType.ADR_DECISION,
    "alternatives": DocumentNodeType.ADR_ALTERNATIVES,
    "consequences": DocumentNodeType.ADR_CONSEQUENCES,
}

_STATUS_MAP = {
    "accepted": DecisionStatus.ACCEPTED,
    "proposed": DecisionStatus.PROPOSED,
    "superseded": DecisionStatus.SUPERSEDED,
    "rejected": DecisionStatus.REJECTED,
    "deprecated": DecisionStatus.DEPRECATED,
}


class AdrParser:
    """Wraps a Markdown parser and re-tags ADR section nodes."""

    name = "adr"

    def __init__(self, markdown_parser: DocumentParser) -> None:
        self._markdown = markdown_parser

    def can_parse(self, artifact: SourceArtifact) -> bool:
        name = (artifact.file_name or artifact.source_uri).lower()
        if not self._markdown.can_parse(artifact):
            return False
        return "adr" in name or name.startswith(("decisions/", "docs/adr"))

    def parse(self, artifact: SourceArtifact) -> ParsedDocument:
        parsed = self._markdown.parse(artifact)
        title = parsed.title or _title_from_uri(artifact)
        parsed.title = title
        sections = self._extract_sections(parsed.nodes, title)
        parsed.adr_sections = sections
        parsed.front_matter.setdefault("adr", True)
        parsed.front_matter.setdefault("adr_title", title)
        parsed.front_matter.setdefault("adr_status", sections.status or "proposed")
        return parsed

    def extract_sections(self, parsed: ParsedDocument) -> AdrSections:
        return self._extract_sections(parsed.nodes, parsed.title or "")

    def _extract_sections(self, nodes: list[ParsedNode], title: str) -> AdrSections:
        context: list[str] = []
        decision: list[str] = []
        alternatives: list[str] = []
        consequences: list[str] = []
        status: str | None = None

        current: str | None = None
        for i, node in enumerate(nodes):
            section = _classify_section(node)
            if section is not None:
                current = section
                if section == "status":
                    status = _section_content(node, nodes, i)
                node_type = _SECTION_NODE_TYPES.get(section)
                if node_type is not None:
                    node.node_type = node_type
                continue
            text = (node.content or node.title or "").strip()
            if not text:
                continue
            if current is None and node.heading_path:
                candidate = node.heading_path[-1].lower().rstrip(":")
                current = _SECTION_HEADINGS.get(candidate)
            if current == "context":
                context.append(text)
            elif current == "decision":
                decision.append(text)
            elif current == "alternatives":
                alternatives.append(text)
            elif current == "consequences":
                consequences.append(text)

        return AdrSections(
            context="\n".join(context).strip(),
            decision="\n".join(decision).strip(),
            alternatives=alternatives,
            consequences=consequences,
            status=status,
        )

    def status(self, value: str | None) -> DecisionStatus:
        if not value:
            return DecisionStatus.PROPOSED
        return _STATUS_MAP.get(value.strip().lower(), DecisionStatus.PROPOSED)


def _classify_section(node: ParsedNode) -> str | None:
    if node.node_type != DocumentNodeType.SECTION:
        return None
    title = (node.title or "").strip().lower().rstrip(":")
    return _SECTION_HEADINGS.get(title)


def _section_content(node: ParsedNode, nodes: list[ParsedNode], index: int) -> str:
    """Return a section heading node's direct text content (following paragraph)."""
    content = (node.content or "").strip()
    if content:
        return content
    for child in nodes[index + 1 :]:
        if child.node_type != DocumentNodeType.PARAGRAPH:
            break
        text = (child.content or "").strip()
        if text:
            return text
    return ""


def _title_from_uri(artifact: SourceArtifact) -> str:
    name = artifact.file_name or artifact.source_uri.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()


__all__ = ["AdrParser"]
