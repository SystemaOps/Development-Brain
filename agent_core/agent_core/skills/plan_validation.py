from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from agent_core.domain.enums import PlanNodeKind
from agent_core.schemas import ProjectPlanSpec
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class PlanValidationInput(BaseModel):
    plan: dict[str, Any]
    enforce_task_acceptance_criteria: bool = True


class PlanValidationFinding(BaseModel):
    severity: str
    code: str
    message: str
    stable_key: str | None = None


class PlanValidationOutput(BaseModel):
    valid: bool
    node_count: int
    dependency_count: int
    findings: list[PlanValidationFinding] = Field(default_factory=list)


class PlanValidationSkill(BaseSkill):
    name = "plan_validation"
    description = "Validates plan hierarchy, dependencies, cycles, and acceptance criteria."
    input_schema = PlanValidationInput
    output_schema = PlanValidationOutput
    side_effects = False

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if any(word in lowered for word in ["validate", "dependency", "cycle", "acceptance criteria"]):
            return 0.9
        return 0.32

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = PlanValidationInput.model_validate(input_data or {})
        output = validate_plan(
            parsed.plan,
            enforce_task_acceptance_criteria=parsed.enforce_task_acceptance_criteria,
        )
        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            errors=[finding.message for finding in output.findings if finding.severity == "error"],
        )


def validate_plan(
    plan: dict[str, Any],
    *,
    enforce_task_acceptance_criteria: bool = True,
) -> PlanValidationOutput:
    findings: list[PlanValidationFinding] = []
    nodes = list(plan.get("nodes") or [])
    node_count = len(nodes)
    dependency_count = sum(len(node.get("dependencies") or []) for node in nodes)

    try:
        ProjectPlanSpec.model_validate(plan)
    except ValidationError as exc:
        findings.append(
            PlanValidationFinding(
                severity="error",
                code="schema_invalid",
                message=str(exc.errors()[0].get("msg", "Plan schema validation failed")),
            )
        )

    by_key: dict[str, dict[str, Any]] = {}
    for node in nodes:
        key = node.get("stable_key")
        if not key:
            findings.append(
                PlanValidationFinding(
                    severity="error",
                    code="missing_stable_key",
                    message="A plan node is missing stable_key.",
                )
            )
            continue
        if key in by_key:
            findings.append(
                PlanValidationFinding(
                    severity="error",
                    code="duplicate_stable_key",
                    message=f"Duplicate plan node stable_key: {key}",
                    stable_key=key,
                )
            )
        by_key[str(key)] = node

    visions = [node for node in nodes if node.get("kind") == PlanNodeKind.VISION.value]
    if len(visions) != 1:
        findings.append(
            PlanValidationFinding(
                severity="error",
                code="invalid_vision_count",
                message="Plan must contain exactly one Vision node.",
            )
        )

    allowed_parent = {
        PlanNodeKind.CAPABILITY.value: PlanNodeKind.VISION.value,
        PlanNodeKind.EPIC.value: PlanNodeKind.CAPABILITY.value,
        PlanNodeKind.STORY.value: PlanNodeKind.EPIC.value,
        PlanNodeKind.TASK.value: PlanNodeKind.STORY.value,
    }
    for node in nodes:
        key = str(node.get("stable_key") or "")
        kind = str(node.get("kind") or "")
        parent_key = node.get("parent_stable_key")
        if kind == PlanNodeKind.VISION.value:
            if parent_key:
                findings.append(
                    PlanValidationFinding(
                        severity="error",
                        code="vision_has_parent",
                        message="Vision nodes cannot have a parent.",
                        stable_key=key,
                    )
                )
        elif kind in allowed_parent:
            if not parent_key or parent_key not in by_key:
                findings.append(
                    PlanValidationFinding(
                        severity="error",
                        code="missing_parent",
                        message=f"Node {key} is missing a valid parent.",
                        stable_key=key,
                    )
                )
            elif by_key[str(parent_key)].get("kind") != allowed_parent[kind]:
                findings.append(
                    PlanValidationFinding(
                        severity="error",
                        code="invalid_parent_level",
                        message=f"Node {key} has an invalid parent level.",
                        stable_key=key,
                    )
                )
        else:
            findings.append(
                PlanValidationFinding(
                    severity="error",
                    code="unknown_node_kind",
                    message=f"Node {key} has unknown kind: {kind}",
                    stable_key=key,
                )
            )

        if kind == PlanNodeKind.TASK.value and enforce_task_acceptance_criteria:
            if not node.get("acceptance_criteria"):
                findings.append(
                    PlanValidationFinding(
                        severity="error",
                        code="missing_acceptance_criteria",
                        message=f"Task {key} must include acceptance criteria.",
                        stable_key=key,
                    )
                )

        for dependency in node.get("dependencies") or []:
            if dependency not in by_key:
                findings.append(
                    PlanValidationFinding(
                        severity="error",
                        code="unknown_dependency",
                        message=f"Node {key} depends on unknown node {dependency}.",
                        stable_key=key,
                    )
                )

    for cycle in _dependency_cycles(nodes):
        findings.append(
            PlanValidationFinding(
                severity="error",
                code="dependency_cycle",
                message="Dependency cycle detected: " + " -> ".join(cycle),
                stable_key=cycle[0] if cycle else None,
            )
        )

    has_errors = any(finding.severity == "error" for finding in findings)
    return PlanValidationOutput(
        valid=not has_errors,
        node_count=node_count,
        dependency_count=dependency_count,
        findings=findings,
    )


def _dependency_cycles(nodes: list[dict[str, Any]]) -> list[list[str]]:
    graph: dict[str, list[str]] = {
        str(node.get("stable_key")): [str(dep) for dep in (node.get("dependencies") or [])]
        for node in nodes
        if node.get("stable_key")
    }
    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(key: str) -> None:
        if key in visiting:
            if key in stack:
                cycles.append(stack[stack.index(key) :] + [key])
            return
        if key in visited:
            return
        visiting.add(key)
        stack.append(key)
        for dependency in graph.get(key, []):
            if dependency in graph:
                visit(dependency)
        stack.pop()
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
    return cycles
