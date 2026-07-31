from __future__ import annotations

from pydantic import BaseModel, Field

from agent_core.llm import StructuredLLM
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class ClarificationQuestion(BaseModel):
    question_key: str
    question: str
    reason: str
    blocking: bool = True
    answer_format: str | None = None


class AmbiguityOutput(BaseModel):
    is_clear_enough: bool
    understood_goal: str
    questions: list[ClarificationQuestion] = Field(default_factory=list)


AMBIGUITY_PROMPT = """
You are the ambiguity assessment skill.

Do not create a plan. Determine whether the input is clear enough to create
a useful software project plan.

Ask only blocking questions that materially affect:
- scope
- users
- data ownership
- architecture
- integrations
- security
- acceptance criteria

Return structured JSON.
"""


class AmbiguityAssessmentSkill(BaseSkill):
    name = "ambiguity_assessment"
    description = "Detects whether planning input is clear enough or needs questions."
    output_schema = AmbiguityOutput
    side_effects = False

    def __init__(self, llm: StructuredLLM):
        self.llm = llm

    def can_handle(self, intent: str, context: SkillContext) -> float:
        keywords = ["unclear", "clarify", "question", "ambiguous", "intake"]
        if any(word in intent.lower() for word in keywords):
            return 0.9
        return 0.6

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict,
    ) -> SkillResult:
        output = await self.llm.generate(
            system=AMBIGUITY_PROMPT,
            user=str(input_data),
            output_model=AmbiguityOutput,
        )

        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            questions=[
                q.model_dump(mode="json")
                for q in output.questions
                if q.blocking
            ],
        )