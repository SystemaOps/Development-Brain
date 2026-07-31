from __future__ import annotations

from collections.abc import Iterable

from agent_core.config.agent_definitions import (
    DEFAULT_AGENT_DEFINITIONS,
    AgentDefinition,
)
from agent_core.skills.registry import SkillRegistry


class AgentRegistry:
    def __init__(self, definitions: Iterable[AgentDefinition] = DEFAULT_AGENT_DEFINITIONS):
        self._definitions = {definition.name: definition for definition in definitions}

    def get(self, name: str) -> AgentDefinition:
        if name not in self._definitions:
            raise KeyError(f"Unknown agent definition: {name}")
        return self._definitions[name]

    def names(self) -> list[str]:
        return sorted(self._definitions)

    def validate_against_skills(self, skill_registry: SkillRegistry) -> None:
        declared = set(skill_registry.manifest_names())
        failures: dict[str, list[str]] = {}
        for definition in self._definitions.values():
            missing = sorted(set(definition.allowed_skills) - declared)
            if missing:
                failures[definition.name] = missing

        if failures:
            details = "; ".join(
                f"{agent}: {', '.join(missing)}"
                for agent, missing in sorted(failures.items())
            )
            raise ValueError(f"Agent definitions reference missing skill manifests: {details}")
