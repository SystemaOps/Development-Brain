from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from agent_core.services.repository_projection_service import REPOSITORY_CONTEXT_COLLECTION
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


PLAN_CONTEXT_COLLECTION = "PlanNodeContext"


class WeaviateProjectionInput(BaseModel):
    project_key: str | None = None
    plan: dict[str, Any]
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    context_capsules: list[dict[str, Any]] = Field(default_factory=list)


class WeaviateUpsertSpec(BaseModel):
    collection: str
    object_id: str
    text: str
    properties: dict[str, Any] = Field(default_factory=dict)


class WeaviateProjectionOutput(BaseModel):
    project_key: str
    upsert_count: int
    upserts: list[WeaviateUpsertSpec] = Field(default_factory=list)


class WeaviateProjectionSkill(BaseSkill):
    name = "weaviate_projection"
    description = "Builds Weaviate upsert specs for planning memory and context."
    input_schema = WeaviateProjectionInput
    output_schema = WeaviateProjectionOutput
    side_effects = False

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if "weaviate" in lowered or "vector" in lowered:
            return 0.9
        if "projection" in lowered or "semantic" in lowered:
            return 0.58
        return 0.18

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = WeaviateProjectionInput.model_validate(input_data or {})
        project_key = parsed.project_key or context.project_key
        upserts: list[WeaviateUpsertSpec] = []
        for node in parsed.plan.get("nodes") or []:
            stable_key = str(node.get("stable_key") or "")
            if not stable_key:
                continue
            text = _plan_node_text(node)
            upserts.append(
                WeaviateUpsertSpec(
                    collection=PLAN_CONTEXT_COLLECTION,
                    object_id=_stable_id(f"plan:{project_key}:{stable_key}"),
                    text=text,
                    properties={
                        "project_key": project_key,
                        "stable_key": stable_key,
                        "kind": node.get("kind"),
                        "title": node.get("title"),
                    },
                )
            )
        for requirement in parsed.requirements:
            req_key = str(requirement.get("key") or "unknown")
            text = str(requirement.get("statement") or requirement.get("text") or req_key)
            upserts.append(
                WeaviateUpsertSpec(
                    collection="ProjectMemory",
                    object_id=_stable_id(f"requirement:{project_key}:{req_key}"),
                    text=text,
                    properties={
                        "project_key": project_key,
                        "memory_id": req_key,
                        "source_type": "requirement",
                        "title": req_key,
                        "summary": text[:300],
                        "tags": ["requirement"],
                    },
                )
            )
        for capsule in parsed.context_capsules:
            node_key = str(capsule.get("plan_node_key") or capsule.get("plan_node_id") or "unknown")
            text = str(capsule.get("content") or "")
            if not text:
                continue
            upserts.append(
                WeaviateUpsertSpec(
                    collection=REPOSITORY_CONTEXT_COLLECTION if capsule.get("capsule_type") == "repository" else "ContextCapsule",
                    object_id=_stable_id(f"capsule:{project_key}:{node_key}:{capsule.get('capsule_type', 'planning')}"),
                    text=text,
                    properties={
                        "project_key": project_key,
                        "plan_node_id": node_key,
                        "capsule_type": capsule.get("capsule_type", "planning"),
                    },
                )
            )
        output = WeaviateProjectionOutput(project_key=project_key, upsert_count=len(upserts), upserts=upserts)
        return SkillResult(skill_name=self.name, success=True, output=output.model_dump(mode="json"))


def _plan_node_text(node: dict[str, Any]) -> str:
    lines = [
        f"{node.get('kind', 'node')}: {node.get('title', node.get('stable_key', 'untitled'))}",
        f"Objective: {node.get('objective', 'Not specified')}",
    ]
    criteria = node.get("acceptance_criteria") or []
    if criteria:
        lines.append("Acceptance criteria:")
        lines.extend(f"- {item.get('statement', item)}" for item in criteria)
    return "\n".join(lines)


def _stable_id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ada:weaviate-projection:{value}"))
