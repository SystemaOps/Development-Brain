from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_core.skills.base import SkillContext, SkillResult
from agent_core.skills.registry import SkillRegistry


class SkillNodeAdapter:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    async def run(
        self,
        *,
        skill_name: str,
        intent: str,
        context: SkillContext,
        input_data: Mapping[str, Any],
    ) -> SkillResult:
        skill = self.registry.get(skill_name)
        parsed_input = skill.validate_input(dict(input_data))
        if hasattr(parsed_input, "model_dump"):
            payload = parsed_input.model_dump(mode="json")
        else:
            payload = parsed_input

        result = await skill.run(
            intent=intent,
            context=context,
            input_data=payload,
        )
        return skill.validate_result(result)
