from __future__ import annotations

from agent_core.agent_platform.factory.builders import AgentBuilder


class AgentBuilderRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, AgentBuilder] = {}

    def register(self, agent_type: str, builder: AgentBuilder) -> None:
        normalized = agent_type.strip()
        if not normalized:
            raise ValueError("agent_type cannot be blank")
        if normalized in self._builders:
            raise ValueError(f"Agent builder already registered: {normalized}")
        if builder.agent_type != normalized:
            raise ValueError(
                f"Builder type '{builder.agent_type}' does not match registration type '{normalized}'"
            )
        self._builders[normalized] = builder

    def get(self, agent_type: str) -> AgentBuilder:
        try:
            return self._builders[agent_type]
        except KeyError as exc:
            raise KeyError(f"Unknown agent type: {agent_type}") from exc

    def names(self) -> list[str]:
        return sorted(self._builders)
