from __future__ import annotations

from agent_core.llm import StructuredLLM
from agent_core.schemas import ProjectPlanSpec
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


PLANNING_PROMPT = """
You are the planning decomposition skill.

Create a versioned plan using this hierarchy:

Vision -> Capability -> Epic -> Story -> Task

Rules:
- exactly one Vision
- Capability children under Vision
- Epic children under Capability
- Story children under Epic
- Task children under Story
- every Task must have acceptance criteria
- preserve inherited context
- expose requirements, constraints, decisions, assumptions, risks, and components
- do not hide assumptions
"""


class PlanningDecompositionSkill(BaseSkill):
    name = "planning_decomposition"
    description = "Creates Vision → Capability → Epic → Story → Task plans."
    output_schema = ProjectPlanSpec
    side_effects = False

    def __init__(self, llm: StructuredLLM):
        self.llm = llm

    def can_handle(self, intent: str, context: SkillContext) -> float:
        keywords = ["plan", "break down", "epic", "story", "task", "decompose"]
        if any(word in intent.lower() for word in keywords):
            return 0.95
        return 0.3

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict,
    ) -> SkillResult:
        plan = await self.llm.generate(
            system=PLANNING_PROMPT,
            user=str(input_data),
            output_model=ProjectPlanSpec,
        )

        return SkillResult(
            skill_name=self.name,
            success=True,
            output=plan.model_dump(mode="json"),
        )