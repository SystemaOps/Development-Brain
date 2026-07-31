from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.ingestion.markdown_splitter import estimate_tokens
from agent_core.models import ContextCapsule, PlanNode, PlanNodeRelation, PlanVersion, Project


class ContextCapsuleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_for_node(self, plan_node_id: UUID, capsule_type: str = "execution") -> ContextCapsule:
        node = await self.db.get(PlanNode, plan_node_id)
        if not node:
            raise KeyError(plan_node_id)
        project = await self.db.get(Project, node.project_id)
        version = await self.db.get(PlanVersion, node.plan_version_id)
        parent_relations = await self.db.scalars(select(PlanNodeRelation).where(
            PlanNodeRelation.from_node_id == node.id,
            PlanNodeRelation.relation_type == "child_of",
        ))
        parent_lines = []
        for rel in parent_relations:
            parent = await self.db.get(PlanNode, rel.to_node_id)
            parent_lines.append(f"- {parent.kind}: {parent.title} — {parent.objective}")
        content = "\\n".join([
            f"Project: {project.name} ({project.project_key})",
            f"Plan version: {version.version_number}",
            "",
            "Parent context:",
            *(parent_lines or ["- None"]),
            "",
            f"Current node: {node.kind} — {node.title}",
            f"Objective: {node.objective}",
            f"Rationale: {node.rationale or 'Not specified'}",
            "",
            "Inherited context:",
            *(f"- {x}" for x in (node.inherited_context or ["None"])),
            "",
            "Expected outputs:",
            *(f"- {x}" for x in (node.expected_outputs or ["None"])),
        ])
        capsule = ContextCapsule(
            project_id=node.project_id,
            plan_version_id=node.plan_version_id,
            plan_node_id=node.id,
            capsule_type=capsule_type,
            content=content,
            capsule_json={"project_key": project.project_key, "plan_node_id": str(node.id)},
            source_refs=[{"type": "plan_node", "id": str(node.id)}],
            token_estimate=estimate_tokens(content),
        )
        self.db.add(capsule)
        await self.db.commit()
        await self.db.refresh(capsule)
        return capsule
