from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    objective: str
    allowed_skills: tuple[str, ...]
    read_only: bool = True
    metadata: dict[str, str] = field(default_factory=dict)


DEFAULT_AGENT_DEFINITIONS: tuple[AgentDefinition, ...] = (
    AgentDefinition(
        name="planning",
        objective="Extract requirements, resolve ambiguity, and produce a validated plan.",
        allowed_skills=(
            "document_ingestion",
            "requirement_extraction",
            "ambiguity_assessment",
            "repository_inspection",
            "implementation_status_classification",
            "planning_decomposition",
            "plan_validation",
            "openproject_projection",
            "neo4j_projection",
            "weaviate_projection",
            "context_capsule",
        ),
        read_only=True,
    ),
    AgentDefinition(
        name="coding",
        objective="Implement approved tasks inside configured repository boundaries.",
        allowed_skills=(),
        read_only=False,
    ),
    AgentDefinition(
        name="verification",
        objective="Verify implementation evidence against requirements and acceptance criteria.",
        allowed_skills=(),
        read_only=True,
    ),
)
