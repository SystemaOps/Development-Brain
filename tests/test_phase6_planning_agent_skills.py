from __future__ import annotations

from typing import Any

import pytest

from agent_core.domain.enums import ImplementationStatus
from agent_core.skills.base import SkillContext


class FakeLLM:
    async def generate(self, **kwargs):
        raise AssertionError("Phase 6 deterministic skill tests must not call the LLM")


def _sample_plan() -> dict[str, Any]:
    return {
        "summary": "Checkout planning slice",
        "nodes": [
            {
                "stable_key": "vision.checkout",
                "kind": "vision",
                "title": "Checkout vision",
                "objective": "Support checkout planning.",
            },
            {
                "stable_key": "capability.checkout",
                "kind": "capability",
                "title": "Checkout capability",
                "objective": "Plan checkout capability.",
                "parent_stable_key": "vision.checkout",
            },
            {
                "stable_key": "epic.checkout",
                "kind": "epic",
                "title": "Checkout epic",
                "objective": "Deliver checkout workflow.",
                "parent_stable_key": "capability.checkout",
            },
            {
                "stable_key": "story.checkout-total",
                "kind": "story",
                "title": "Checkout total story",
                "objective": "Users can see a calculated checkout total.",
                "parent_stable_key": "epic.checkout",
            },
            {
                "stable_key": "task.checkout-total",
                "kind": "task",
                "title": "Calculate checkout total",
                "objective": "Implement total calculation for checkout.",
                "parent_stable_key": "story.checkout-total",
                "acceptance_criteria": [
                    {
                        "key": "ac.checkout-total",
                        "statement": "Checkout total is calculated and covered by tests.",
                        "verification_method": "pytest",
                    }
                ],
            },
        ],
    }


def test_phase6_manifests_are_implemented_and_registry_runnable(monkeypatch):
    from agent_core.skills import build_skill_registry
    from agent_core.skills.manifest import load_builtin_skill_manifests

    manifests = load_builtin_skill_manifests()
    phase6_skill_names = {
        "requirement_extraction",
        "repository_inspection",
        "implementation_status_classification",
        "plan_validation",
        "openproject_projection",
        "neo4j_projection",
        "weaviate_projection",
        "context_capsule",
    }

    assert {name for name in phase6_skill_names if manifests[name].status == "implemented"} == phase6_skill_names

    registry = build_skill_registry(llm=FakeLLM())
    runnable = set(registry.runnable_names())
    assert phase6_skill_names.issubset(runnable)
    assert "document_ingestion" not in runnable


@pytest.mark.asyncio
async def test_requirement_extraction_preserves_chunk_evidence():
    from agent_core.skills.requirement_extraction import RequirementExtractionSkill

    result = await RequirementExtractionSkill().run(
        intent="extract requirements",
        context=SkillContext(project_key="checkout-demo"),
        input_data={
            "original_request": "Build checkout support for carts.",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "title": "Requirements",
                    "heading_path": ["Requirements"],
                    "content": "- The system must calculate checkout totals.\n- Security constraint: payment tokens must not be stored.",
                },
                {
                    "chunk_id": "chunk-2",
                    "title": "Risks",
                    "heading_path": ["Risks"],
                    "content": "- Risk: tax integration may be unavailable.",
                },
            ],
        },
    )

    assert result.success
    document_requirement = next(
        item
        for item in result.output["requirements"]
        if item["statement"] == "The system must calculate checkout totals."
    )
    assert document_requirement["evidence"][0]["uri"] == "document_chunk:chunk-1"
    assert result.output["constraints"][0]["key"].startswith("con.")
    assert result.output["risks"][0]["key"].startswith("risk.")


@pytest.mark.asyncio
async def test_repository_inspection_feeds_implementation_status_classification():
    from agent_core.skills.implementation_status_classification import (
        ImplementationStatusClassificationSkill,
    )
    from agent_core.skills.repository_inspection import RepositoryInspectionSkill

    symbols = [
        {
            "symbol_key": "sample:function:src/cart.py:calculate_total:10",
            "repository_key": "sample",
            "relative_path": "src/cart.py",
            "name": "calculate_total",
            "kind": "function",
            "language": "python",
            "start_line": 10,
        },
        {
            "symbol_key": "sample:function:tests/test_cart.py:test_calculate_total:4",
            "repository_key": "sample",
            "relative_path": "tests/test_cart.py",
            "name": "test_calculate_total",
            "kind": "function",
            "language": "python",
            "start_line": 4,
        },
    ]
    inspection = await RepositoryInspectionSkill().run(
        intent="inspect repository",
        context=SkillContext(project_key="checkout-demo"),
        input_data={"repository_key": "sample", "symbols": symbols},
    )

    classification = await ImplementationStatusClassificationSkill().run(
        intent="classify implementation status",
        context=SkillContext(project_key="checkout-demo"),
        input_data={
            "requirements": [
                {"key": "req.total", "statement": "The system must calculate checkout total."},
                {"key": "req.email", "statement": "The system must send receipt email."},
            ],
            "repository_inspection": inspection.output,
            "min_complete_score": 2,
        },
    )

    statuses = {
        item["requirement_key"]: item["status"]
        for item in classification.output["classifications"]
    }
    assert inspection.output["summary"]["test_symbol_count"] == 1
    assert statuses["req.total"] == ImplementationStatus.COMPLETE.value
    assert statuses["req.email"] == ImplementationStatus.MISSING.value


@pytest.mark.asyncio
async def test_plan_validation_detects_missing_acceptance_and_dependency_cycle():
    from agent_core.skills.plan_validation import PlanValidationSkill

    invalid_plan = _sample_plan()
    invalid_plan["nodes"][-1]["acceptance_criteria"] = []
    invalid_plan["nodes"][-1]["dependencies"] = ["story.checkout-total"]
    invalid_plan["nodes"][-2]["dependencies"] = ["task.checkout-total"]

    result = await PlanValidationSkill().run(
        intent="validate dependencies",
        context=SkillContext(project_key="checkout-demo"),
        input_data={"plan": invalid_plan},
    )

    codes = {finding["code"] for finding in result.output["findings"]}
    assert result.success
    assert result.output["valid"] is False
    assert "missing_acceptance_criteria" in codes
    assert "dependency_cycle" in codes


@pytest.mark.asyncio
async def test_context_capsule_and_projection_skills_build_idempotent_specs():
    from agent_core.skills.context_capsule import ContextCapsuleSkill
    from agent_core.skills.neo4j_projection import Neo4jProjectionSkill
    from agent_core.skills.openproject_projection import OpenProjectProjectionSkill
    from agent_core.skills.weaviate_projection import WeaviateProjectionSkill

    plan = _sample_plan()
    task = plan["nodes"][-1]
    requirement = {
        "key": "req.total",
        "statement": "The system must calculate checkout total.",
        "evidence": [
            {
                "evidence_type": "document_chunk",
                "uri": "document_chunk:chunk-1",
                "title": "Requirements",
            }
        ],
    }
    implementation = {
        "requirement_key": "req.total",
        "status": "complete",
        "rationale": "Matched implementation and test evidence.",
    }
    repository_evidence = {
        "evidence_type": "code_symbol",
        "uri": "repository://sample/src/cart.py#calculate_total",
        "name": "calculate_total",
        "kind": "function",
    }

    capsule = await ContextCapsuleSkill().run(
        intent="build context capsule",
        context=SkillContext(project_key="checkout-demo"),
        input_data={
            "plan_node": task,
            "requirements": [requirement],
            "implementation_statuses": [implementation],
            "repository_evidence": [repository_evidence],
        },
    )
    openproject = await OpenProjectProjectionSkill().run(
        intent="build OpenProject projection",
        context=SkillContext(project_key="checkout-demo"),
        input_data={"plan": plan, "version_number": 3},
    )
    neo4j = await Neo4jProjectionSkill().run(
        intent="build Neo4j projection",
        context=SkillContext(project_key="checkout-demo"),
        input_data={
            "plan": plan,
            "requirements": [requirement],
            "implementation_statuses": [implementation],
        },
    )
    weaviate = await WeaviateProjectionSkill().run(
        intent="build Weaviate projection",
        context=SkillContext(project_key="checkout-demo"),
        input_data={
            "plan": plan,
            "requirements": [requirement],
            "context_capsules": [capsule.output],
        },
    )

    assert "Requirement" in capsule.output["content"]
    assert openproject.output["operation_count"] == 3
    assert openproject.output["operations"][-1]["idempotency_key"] == "openproject:checkout-demo:plan-v3:task.checkout-total"
    assert any(node["labels"] == ["Requirement"] for node in neo4j.output["nodes"])
    assert weaviate.output["upsert_count"] == len(plan["nodes"]) + 2
    assert all(item["object_id"] for item in weaviate.output["upserts"])
