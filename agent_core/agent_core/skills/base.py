from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class SkillContext(BaseModel):
    project_key: str
    session_id: str | None = None
    plan_version_id: str | None = None
    node_identity_id: str | None = None

    # References only. Do not put huge documents here.
    document_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    skill_name: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class BaseSkill(ABC):
    name: str
    description: str
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None
    side_effects: bool = False

    def validate_input(self, input_data: dict[str, Any]) -> BaseModel | dict[str, Any]:
        if self.input_schema is None:
            return input_data
        return self.input_schema.model_validate(input_data)

    def validate_result(self, result: SkillResult) -> SkillResult:
        if result.skill_name != self.name:
            raise ValueError(
                f"Skill {self.name} returned result for {result.skill_name}"
            )
        if result.success and self.output_schema is not None:
            try:
                self.output_schema.model_validate(result.output)
            except ValidationError as exc:
                raise ValueError(
                    f"Skill {self.name} returned invalid output"
                ) from exc
        return result

    @abstractmethod
    def can_handle(self, intent: str, context: SkillContext) -> float:
        """
        Return confidence between 0.0 and 1.0.
        """

    @abstractmethod
    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        """
        Execute the skill.
        """
