"""Parser registry and selection policy (Task 5.2).

:class:`ParserRegistry` holds every registered :class:`DocumentParser` and
delegates selection to a :class:`ParserSelectionPolicy`.  The default policy
picks the first parser that ``can_parse`` the artifact, so registration order
matters: specific parsers (ADR) should be registered before generic ones
(Markdown).
"""

from __future__ import annotations

from collections.abc import Sequence

from brain.domain.documents import SourceArtifact
from brain.ports.parsing import DocumentParser, ParserSelectionPolicy


class DefaultParserSelectionPolicy:
    """First parser that accepts the artifact wins."""

    def select(
        self, parsers: Sequence[DocumentParser], artifact: SourceArtifact
    ) -> DocumentParser | None:
        for parser in parsers:
            if parser.can_parse(artifact):
                return parser
        return None


class DefaultParserRegistry:
    def __init__(
        self,
        *,
        selection_policy: ParserSelectionPolicy | None = None,
    ) -> None:
        self._parsers: list[DocumentParser] = []
        self._policy = selection_policy or DefaultParserSelectionPolicy()

    def register(self, parser: DocumentParser) -> None:
        if parser not in self._parsers:
            self._parsers.append(parser)

    def select(self, artifact: SourceArtifact) -> DocumentParser | None:
        return self._policy.select(self._parsers, artifact)

    def list(self) -> list[DocumentParser]:
        return list(self._parsers)


__all__ = ["DefaultParserRegistry", "DefaultParserSelectionPolicy"]
