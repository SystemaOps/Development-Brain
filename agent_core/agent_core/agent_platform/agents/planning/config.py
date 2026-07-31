from __future__ import annotations

from pydantic import Field

from agent_core.agent_platform.config.models import AgentConfig


class PlanningAgentConfig(AgentConfig):
    agent_type: str = "planning"
    checkpoint_namespace: str = "planning"
    approval_required: bool = True
    require_plan_validation: bool = True
    allow_legacy_planning_service: bool = True
    skill_names: list[str] = Field(
        default_factory=lambda: [
            "document_ingestion",
            "requirement_extraction",
            "ambiguity_assessment",
            "repository_inspection",
            "implementation_status_classification",
            "planning_decomposition",
            "plan_validation",
            "context_capsule",
            "openproject_projection",
            "neo4j_projection",
            "weaviate_projection",
        ]
    )
