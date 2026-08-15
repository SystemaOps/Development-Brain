"""Default (no-op) entity extractor (Task 5.7).

The pipeline exposes :class:`~brain.ports.parsing.EntityExtractor` as an
extension point: ``ParsedDocument -> candidate requirements``.  The default
implementation returns no candidates so the pipeline is LLM-free; an
LLM-backed extractor can replace it later without changing the pipeline.
"""

from __future__ import annotations

from brain.domain.parsing import CandidateRequirement, ParsedDocument


class NoopEntityExtractor:
    """Returns no candidate requirements."""

    def extract(self, parsed: ParsedDocument) -> list[CandidateRequirement]:
        return []


__all__ = ["NoopEntityExtractor"]
