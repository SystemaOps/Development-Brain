from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.enums import PlanNodeKind
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class OpenProjectProjectionInput(BaseModel):
    project_key: str | None = None
    openproject_project_identifier: str | None = None
    plan: dict[str, Any]
    version_number: int = 1


class OpenProjectProjectionOperation(BaseModel):
    idempotency_key: str
    operation_type: str
    artifact_type: str
    stable_key: str
    payload: dict[str, Any]


class OpenProjectProjectionOutput(BaseModel):
    project_key: str
    operation_count: int
    operations: list[OpenProjectProjectionOperation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OpenProjectProjectionSkill(BaseSkill):
    name = "openproject_projection"
    description = "Builds idempotent OpenProject work-package operation specs from a plan."
    input_schema = OpenProjectProjectionInput
    output_schema = OpenProjectProjectionOutput
    side_effects = False

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if "openproject" in lowered or "work package" in lowered:
            return 0.9
        if "project" in lowered and "projection" in lowered:
            return 0.72
        return 0.22

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = OpenProjectProjectionInput.model_validate(input_data or {})
        project_key = parsed.project_key or context.project_key
        operations: list[OpenProjectProjectionOperation] = []
        warnings: list[str] = []
        for node in parsed.plan.get("nodes") or []:
            kind = str(node.get("kind") or "")
            if kind not in {PlanNodeKind.EPIC.value, PlanNodeKind.STORY.value, PlanNodeKind.TASK.value}:
                continue
            stable_key = str(node.get("stable_key") or "")
            if not stable_key:
                warnings.append("Skipped OpenProject projection node without stable_key.")
                continue
            operations.append(
                OpenProjectProjectionOperation(
                    idempotency_key=f"openproject:{project_key}:plan-v{parsed.version_number}:{stable_key}",
                    operation_type="create_or_update_work_package",
                    artifact_type="work_package",
                    stable_key=stable_key,
                    payload={
                        "subject": node.get("title") or stable_key,
                        "description": {
                            "format": "markdown",
                            "raw": _description_markdown(node),
                        },
                        "metadata": {
                            "project_key": project_key,
                            "openproject_project_identifier": parsed.openproject_project_identifier or project_key,
                            "stable_key": stable_key,
                            "parent_stable_key": node.get("parent_stable_key"),
                            "plan_kind": kind,
                            "dependencies": node.get("dependencies") or [],
                        },
                    },
                )
            )
        output = OpenProjectProjectionOutput(
            project_key=project_key,
            operation_count=len(operations),
            operations=operations,
            warnings=warnings,
        )
        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            errors=warnings,
        )


def _description_markdown(node: dict[str, Any]) -> str:
    lines = [
        f"## Objective\n{node.get('objective') or 'Not specified'}",
    ]
    criteria = node.get("acceptance_criteria") or []
    if criteria:
        lines.append("## Acceptance Criteria")
        lines.extend(f"- {item.get('key', 'ac')}: {item.get('statement', item)}" for item in criteria)
    outputs = node.get("expected_outputs") or []
    if outputs:
        lines.append("## Expected Outputs")
        lines.extend(f"- {item}" for item in outputs)
    return "\n\n".join(lines)
