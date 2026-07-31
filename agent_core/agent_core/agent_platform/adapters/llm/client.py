from __future__ import annotations

from agent_core.ports.llm import StructuredGenerationPort


class LLMClient(StructuredGenerationPort):
    """Platform-facing LLM interface used by agents and skills."""


__all__ = ["LLMClient"]
