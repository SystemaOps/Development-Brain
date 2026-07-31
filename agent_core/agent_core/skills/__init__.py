from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from agent_core.llm import StructuredLLM

_LAZY_EXPORTS = {
    "AmbiguityAssessmentSkill": "agent_core.skills.ambiguity_assessment",
    "ContextCapsuleSkill": "agent_core.skills.context_capsule",
    "DocumentIngestionSkill": "agent_core.skills.document_ingestion",
    "ImplementationStatusClassificationSkill": "agent_core.skills.implementation_status_classification",
    "Neo4jProjectionSkill": "agent_core.skills.neo4j_projection",
    "OpenProjectProjectionSkill": "agent_core.skills.openproject_projection",
    "PlanValidationSkill": "agent_core.skills.plan_validation",
    "PlanningDecompositionSkill": "agent_core.skills.planning_decomposition",
    "RepositoryInspectionSkill": "agent_core.skills.repository_inspection",
    "RequirementExtractionSkill": "agent_core.skills.requirement_extraction",
    "SkillRegistry": "agent_core.skills.registry",
    "WeaviateProjectionSkill": "agent_core.skills.weaviate_projection",
    "load_builtin_skill_manifests": "agent_core.skills.manifest",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def build_skill_registry(
    *,
    db: AsyncSession | None = None,
    include_database_skills: bool = False,
    llm: "StructuredLLM | None" = None,
):
    from agent_core.llm import StructuredLLM
    from agent_core.skills.ambiguity_assessment import AmbiguityAssessmentSkill
    from agent_core.skills.context_capsule import ContextCapsuleSkill
    from agent_core.skills.document_ingestion import DocumentIngestionSkill
    from agent_core.skills.implementation_status_classification import (
        ImplementationStatusClassificationSkill,
    )
    from agent_core.skills.manifest import load_builtin_skill_manifests
    from agent_core.skills.neo4j_projection import Neo4jProjectionSkill
    from agent_core.skills.openproject_projection import OpenProjectProjectionSkill
    from agent_core.skills.plan_validation import PlanValidationSkill
    from agent_core.skills.planning_decomposition import PlanningDecompositionSkill
    from agent_core.skills.registry import SkillRegistry
    from agent_core.skills.repository_inspection import RepositoryInspectionSkill
    from agent_core.skills.requirement_extraction import RequirementExtractionSkill
    from agent_core.skills.weaviate_projection import WeaviateProjectionSkill

    llm_client = llm or StructuredLLM()

    registry = SkillRegistry(load_builtin_skill_manifests())
    registry.register(RequirementExtractionSkill())
    registry.register(AmbiguityAssessmentSkill(llm_client))
    registry.register(RepositoryInspectionSkill(db if include_database_skills else None))
    registry.register(ImplementationStatusClassificationSkill())
    registry.register(PlanningDecompositionSkill(llm_client))
    registry.register(PlanValidationSkill())
    registry.register(OpenProjectProjectionSkill())
    registry.register(Neo4jProjectionSkill())
    registry.register(WeaviateProjectionSkill())
    registry.register(ContextCapsuleSkill())

    if include_database_skills:
        if db is None:
            raise ValueError("Database-backed skills require a database session")
        registry.register(DocumentIngestionSkill(db))

    registry.validate_required_manifests(
        (
            "document_ingestion",
            "requirement_extraction",
            "ambiguity_assessment",
            "repository_inspection",
            "implementation_status_classification",
            "planning_decomposition",
            "dependency_validation",
            "openproject_projection",
            "neo4j_projection",
            "weaviate_projection",
            "context_capsule",
        )
    )

    return registry


__all__ = ["build_skill_registry", *_LAZY_EXPORTS]
