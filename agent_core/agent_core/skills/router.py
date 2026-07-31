from __future__ import annotations

from pydantic import BaseModel

from agent_core.skills.base import BaseSkill, SkillContext
from agent_core.skills.registry import SkillRegistry


class SkillRoute(BaseModel):
    skill_name: str
    confidence: float
    reason: str


class SkillRouter:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def route(self, *, intent: str, context: SkillContext) -> SkillRoute:
        candidates: list[tuple[BaseSkill, float]] = []

        for skill in self.registry.all():
            confidence = skill.can_handle(intent, context)
            candidates.append((skill, confidence))

        candidates.sort(key=lambda item: item[1], reverse=True)

        best_skill, confidence = candidates[0]

        if confidence < 0.4:
            return SkillRoute(
                skill_name="ambiguity_assessment",
                confidence=confidence,
                reason="No skill was confident enough; falling back to clarification.",
            )

        return SkillRoute(
            skill_name=best_skill.name,
            confidence=confidence,
            reason=f"{best_skill.name} had the highest confidence.",
        )