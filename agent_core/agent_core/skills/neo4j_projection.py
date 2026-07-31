from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class Neo4jProjectionInput(BaseModel):
    project_key: str | None = None
    plan: dict[str, Any]
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    implementation_statuses: list[dict[str, Any]] = Field(default_factory=list)


class Neo4jNodeSpec(BaseModel):
    labels: list[str]
    key: str
    properties: dict[str, Any] = Field(default_factory=dict)


class Neo4jRelationSpec(BaseModel):
    from_key: str
    to_key: str
    relation_type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class Neo4jProjectionOutput(BaseModel):
    project_key: str
    nodes: list[Neo4jNodeSpec] = Field(default_factory=list)
    relationships: list[Neo4jRelationSpec] = Field(default_factory=list)


class Neo4jProjectionSkill(BaseSkill):
    name = "neo4j_projection"
    description = "Builds Neo4j projection specs for plans, requirements, and evidence state."
    input_schema = Neo4jProjectionInput
    output_schema = Neo4jProjectionOutput
    side_effects = False

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if "neo4j" in lowered or "graph" in lowered:
            return 0.9
        if "projection" in lowered:
            return 0.62
        return 0.2

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = Neo4jProjectionInput.model_validate(input_data or {})
        project_key = parsed.project_key or context.project_key
        project_node_key = f"project:{project_key}"
        nodes: list[Neo4jNodeSpec] = [
            Neo4jNodeSpec(
                labels=["Project"],
                key=project_node_key,
                properties={"project_key": project_key},
            )
        ]
        relationships: list[Neo4jRelationSpec] = []

        for plan_node in parsed.plan.get("nodes") or []:
            stable_key = str(plan_node.get("stable_key") or "")
            if not stable_key:
                continue
            node_key = f"plan_node:{project_key}:{stable_key}"
            nodes.append(
                Neo4jNodeSpec(
                    labels=["PlanNode", _label(str(plan_node.get("kind") or "Unknown"))],
                    key=node_key,
                    properties={
                        "project_key": project_key,
                        "stable_key": stable_key,
                        "kind": plan_node.get("kind"),
                        "title": plan_node.get("title"),
                        "objective": plan_node.get("objective"),
                    },
                )
            )
            relationships.append(
                Neo4jRelationSpec(
                    from_key=project_node_key,
                    to_key=node_key,
                    relation_type="HAS_PLAN_NODE",
                )
            )
            parent_key = plan_node.get("parent_stable_key")
            if parent_key:
                relationships.append(
                    Neo4jRelationSpec(
                        from_key=node_key,
                        to_key=f"plan_node:{project_key}:{parent_key}",
                        relation_type="CHILD_OF",
                    )
                )
            for dependency in plan_node.get("dependencies") or []:
                relationships.append(
                    Neo4jRelationSpec(
                        from_key=node_key,
                        to_key=f"plan_node:{project_key}:{dependency}",
                        relation_type="DEPENDS_ON",
                    )
                )

        for requirement in parsed.requirements:
            req_key = str(requirement.get("key") or "unknown")
            graph_key = f"requirement:{project_key}:{req_key}"
            nodes.append(
                Neo4jNodeSpec(
                    labels=["Requirement"],
                    key=graph_key,
                    properties={
                        "project_key": project_key,
                        "requirement_key": req_key,
                        "statement": requirement.get("statement") or requirement.get("text"),
                    },
                )
            )
            relationships.append(
                Neo4jRelationSpec(
                    from_key=project_node_key,
                    to_key=graph_key,
                    relation_type="HAS_REQUIREMENT",
                )
            )

        for item in parsed.implementation_statuses:
            req_key = item.get("requirement_key")
            if not req_key:
                continue
            relationships.append(
                Neo4jRelationSpec(
                    from_key=f"requirement:{project_key}:{req_key}",
                    to_key=project_node_key,
                    relation_type="HAS_IMPLEMENTATION_STATUS",
                    properties={
                        "status": item.get("status"),
                        "confidence": item.get("confidence"),
                        "rationale": item.get("rationale"),
                    },
                )
            )

        output = Neo4jProjectionOutput(project_key=project_key, nodes=nodes, relationships=relationships)
        return SkillResult(skill_name=self.name, success=True, output=output.model_dump(mode="json"))


def _label(value: str) -> str:
    return "".join(part.capitalize() for part in value.replace("-", "_").split("_") if part) or "Unknown"
