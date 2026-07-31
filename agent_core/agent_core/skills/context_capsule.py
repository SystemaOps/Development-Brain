from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.evidence import EvidenceRef
from agent_core.ingestion.markdown_splitter import estimate_tokens
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class ContextCapsuleInput(BaseModel):
    project_key: str | None = None
    plan_node: dict[str, Any]
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    implementation_statuses: list[dict[str, Any]] = Field(default_factory=list)
    repository_evidence: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    capsule_type: str = "planning"
    max_chars: int = Field(default=4000, ge=500, le=20000)


class ContextCapsuleOutput(BaseModel):
    project_key: str
    plan_node_key: str
    capsule_type: str
    content: str
    token_estimate: int
    source_refs: list[EvidenceRef] = Field(default_factory=list)
    included_counts: dict[str, int] = Field(default_factory=dict)


class ContextCapsuleSkill(BaseSkill):
    name = "context_capsule"
    description = "Assembles bounded plan-node context from requirements and evidence."
    input_schema = ContextCapsuleInput
    output_schema = ContextCapsuleOutput
    side_effects = False

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if any(word in lowered for word in ["context capsule", "capsule", "task context"]):
            return 0.9
        return 0.26

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = ContextCapsuleInput.model_validate(input_data or {})
        project_key = parsed.project_key or context.project_key
        node_key = str(parsed.plan_node.get("stable_key") or "unknown-node")
        lines = [
            f"Project: {project_key}",
            f"Plan node: {parsed.plan_node.get('kind', 'unknown')} {node_key}",
            f"Title: {parsed.plan_node.get('title', 'Untitled')}",
            f"Objective: {parsed.plan_node.get('objective', 'Not specified')}",
            "",
        ]
        _append_items(lines, "Acceptance Criteria", parsed.plan_node.get("acceptance_criteria") or [], _acceptance_line)
        _append_items(lines, "Requirements", parsed.requirements, _requirement_line)
        _append_items(lines, "Implementation Status", parsed.implementation_statuses, _status_line)
        _append_items(lines, "Repository Evidence", parsed.repository_evidence, _evidence_line)
        _append_items(lines, "Constraints", parsed.constraints, _text_item_line)
        _append_items(lines, "Assumptions", parsed.assumptions, _text_item_line)
        content = "\n".join(lines).strip()
        if len(content) > parsed.max_chars:
            content = content[: parsed.max_chars - 3].rstrip() + "..."

        source_refs = _source_refs(parsed)
        output = ContextCapsuleOutput(
            project_key=project_key,
            plan_node_key=node_key,
            capsule_type=parsed.capsule_type,
            content=content,
            token_estimate=estimate_tokens(content),
            source_refs=source_refs,
            included_counts={
                "requirements": len(parsed.requirements),
                "implementation_statuses": len(parsed.implementation_statuses),
                "repository_evidence": len(parsed.repository_evidence),
                "constraints": len(parsed.constraints),
                "assumptions": len(parsed.assumptions),
            },
        )
        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            source_refs=[ref.model_dump(mode="json") for ref in source_refs],
        )


def _append_items(lines: list[str], heading: str, items: list[dict[str, Any]], formatter) -> None:
    lines.append(f"{heading}:")
    if not items:
        lines.append("- None")
    else:
        for item in items[:20]:
            lines.append(f"- {formatter(item)}")
    lines.append("")


def _acceptance_line(item: dict[str, Any]) -> str:
    return f"{item.get('key', 'ac')}: {item.get('statement', item)}"


def _requirement_line(item: dict[str, Any]) -> str:
    return f"{item.get('key', 'req')}: {item.get('statement') or item.get('text') or item}"


def _status_line(item: dict[str, Any]) -> str:
    return f"{item.get('requirement_key', 'req')}: {item.get('status', 'unknown')} - {item.get('rationale', '')}"


def _evidence_line(item: dict[str, Any]) -> str:
    return f"{item.get('kind', item.get('evidence_type', 'evidence'))} {item.get('name', item.get('title', 'item'))}: {item.get('uri', '')}"


def _text_item_line(item: dict[str, Any]) -> str:
    return f"{item.get('key', 'item')}: {item.get('text') or item.get('statement') or item}"


def _source_refs(parsed: ContextCapsuleInput) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for collection in [parsed.requirements, parsed.implementation_statuses, parsed.repository_evidence, parsed.constraints, parsed.assumptions]:
        for item in collection:
            for raw_ref in item.get("evidence") or []:
                refs.append(EvidenceRef.model_validate(raw_ref))
            uri = item.get("uri")
            if uri:
                refs.append(
                    EvidenceRef(
                        evidence_type=str(item.get("evidence_type") or "planning_evidence"),
                        uri=str(uri),
                        title=item.get("name") or item.get("title") or item.get("key"),
                        excerpt=item.get("excerpt"),
                        metadata=item.get("metadata") or {},
                    )
                )
    deduped: dict[str, EvidenceRef] = {}
    for ref in refs:
        deduped.setdefault(ref.uri, ref)
    return list(deduped.values())
