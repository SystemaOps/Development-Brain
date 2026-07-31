from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel


class FakeInput(BaseModel):
    text: str


class FakeOutput(BaseModel):
    normalized: str


def test_builtin_skill_manifests_cover_required_planning_skills():
    from agent_core.skills.manifest import load_builtin_skill_manifests

    manifests = load_builtin_skill_manifests()

    assert {
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
    }.issubset(manifests)
    assert manifests["ambiguity_assessment"].status == "implemented"
    assert manifests["planning_decomposition"].status == "implemented"
    assert manifests["requirement_extraction"].status == "implemented"


def test_duplicate_skill_manifests_fail_clearly(tmp_path: Path):
    from agent_core.skills.manifest import load_skill_manifests

    payload = {
        "name": "duplicate_skill",
        "version": "1.0.0",
        "description": "duplicate",
        "status": "planned",
    }
    (tmp_path / "a.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate skill manifest"):
        load_skill_manifests(tmp_path)


def test_registry_rejects_skill_registered_against_planned_manifest():
    from agent_core.skills.base import BaseSkill, SkillContext, SkillResult
    from agent_core.skills.manifest import SkillManifest
    from agent_core.skills.registry import SkillRegistry

    class PlannedSkill(BaseSkill):
        name = "planned_skill"
        description = "planned"
        side_effects = False

        def can_handle(self, intent: str, context: SkillContext) -> float:
            return 1.0

        async def run(
            self,
            *,
            intent: str,
            context: SkillContext,
            input_data: dict[str, Any],
        ) -> SkillResult:
            return SkillResult(skill_name=self.name, success=True)

    registry = SkillRegistry(
        {
            "planned_skill": SkillManifest(
                name="planned_skill",
                version="0.1.0",
                description="planned",
                status="planned",
            )
        }
    )

    with pytest.raises(ValueError, match="manifest is planned"):
        registry.register(PlannedSkill())


@pytest.mark.asyncio
async def test_skill_node_adapter_validates_input_and_output():
    from agent_core.skills.base import BaseSkill, SkillContext, SkillResult
    from agent_core.skills.manifest import SkillManifest
    from agent_core.skills.registry import SkillRegistry
    from agent_core.workflow.skill_node import SkillNodeAdapter

    class FakeSkill(BaseSkill):
        name = "fake_skill"
        description = "fake"
        input_schema = FakeInput
        output_schema = FakeOutput

        def can_handle(self, intent: str, context: SkillContext) -> float:
            return 1.0

        async def run(
            self,
            *,
            intent: str,
            context: SkillContext,
            input_data: dict[str, Any],
        ) -> SkillResult:
            return SkillResult(
                skill_name=self.name,
                success=True,
                output={"normalized": input_data["text"].strip().lower()},
            )

    registry = SkillRegistry(
        {
            "fake_skill": SkillManifest(
                name="fake_skill",
                version="1.0.0",
                description="fake",
                input_schema=f"{FakeInput.__module__}.{FakeInput.__qualname__}",
                output_schema=f"{FakeOutput.__module__}.{FakeOutput.__qualname__}",
            )
        }
    )
    registry.register(FakeSkill())

    result = await SkillNodeAdapter(registry).run(
        skill_name="fake_skill",
        intent="normalize",
        context=SkillContext(project_key="demo"),
        input_data={"text": " Hello "},
    )

    assert result.output == {"normalized": "hello"}


def test_agent_registry_references_declared_skill_manifests():
    from agent_core.agents.registry import AgentRegistry
    from agent_core.skills.manifest import load_builtin_skill_manifests
    from agent_core.skills.registry import SkillRegistry

    skill_registry = SkillRegistry(load_builtin_skill_manifests())

    AgentRegistry().validate_against_skills(skill_registry)


def _set_required_settings(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://coding_agent:change-me@localhost:5432/coding_agent",
    )
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("LLM_MODEL", "local-coding-model")
    monkeypatch.setenv("LLM_API_KEY", "local-not-secret")
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "http://localhost:8081")
    monkeypatch.setenv("OPENPROJECT_API_KEY", "placeholder-key")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "change-me")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")


def test_build_skill_registry_can_opt_into_database_backed_skills(monkeypatch):
    _set_required_settings(monkeypatch)

    from agent_core.skills import build_skill_registry

    class FakeLLM:
        async def generate(self, **kwargs):
            raise AssertionError("This test should not call the LLM")

    registry = build_skill_registry(
        db=object(),
        include_database_skills=True,
        llm=FakeLLM(),
    )

    assert "document_ingestion" in registry.runnable_names()


def test_build_skill_registry_requires_db_for_database_backed_skills(monkeypatch):
    _set_required_settings(monkeypatch)

    from agent_core.skills import build_skill_registry

    class FakeLLM:
        async def generate(self, **kwargs):
            raise AssertionError("This test should not call the LLM")

    with pytest.raises(ValueError, match="Database-backed skills require"):
        build_skill_registry(include_database_skills=True, llm=FakeLLM())


@pytest.mark.asyncio
async def test_planning_workflow_executes_with_fake_skill_and_services(monkeypatch):
    _set_required_settings(monkeypatch)

    from langgraph.store.memory import InMemoryStore

    from agent_core.schemas import ProjectPlanSpec
    from agent_core.skills.base import BaseSkill, SkillContext, SkillResult
    from agent_core.skills.manifest import load_builtin_skill_manifests
    from agent_core.skills.registry import SkillRegistry
    from agent_core.workflow.graph import build_planning_graph

    class FakePlanningSkill(BaseSkill):
        name = "planning_decomposition"
        description = "fake planning skill"
        output_schema = ProjectPlanSpec
        side_effects = False

        def can_handle(self, intent: str, context: SkillContext) -> float:
            return 1.0

        async def run(
            self,
            *,
            intent: str,
            context: SkillContext,
            input_data: dict[str, Any],
        ) -> SkillResult:
            return SkillResult(
                skill_name=self.name,
                success=True,
                output={
                    "summary": "Fake plan",
                    "rationale": "Exercise workflow execution without external dependencies.",
                    "nodes": [
                        {
                            "stable_key": "vision.fake",
                            "kind": "vision",
                            "title": "Fake vision",
                            "objective": "Prove fake workflow execution.",
                        },
                        {
                            "stable_key": "capability.fake",
                            "kind": "capability",
                            "title": "Fake capability",
                            "objective": "Support the fake workflow.",
                            "parent_stable_key": "vision.fake",
                        },
                        {
                            "stable_key": "epic.fake",
                            "kind": "epic",
                            "title": "Fake epic",
                            "objective": "Deliver fake workflow coverage.",
                            "parent_stable_key": "capability.fake",
                        },
                        {
                            "stable_key": "story.fake",
                            "kind": "story",
                            "title": "Fake story",
                            "objective": "Exercise graph persistence path.",
                            "parent_stable_key": "epic.fake",
                        },
                        {
                            "stable_key": "task.fake",
                            "kind": "task",
                            "title": "Fake task",
                            "objective": "Persist a fake task.",
                            "parent_stable_key": "story.fake",
                            "acceptance_criteria": [
                                {
                                    "key": "ac.fake",
                                    "statement": "The fake graph completes.",
                                    "verification_method": "unit_test",
                                }
                            ],
                        },
                    ],
                },
            )

    class FakePlanningService:
        async def load_session_context(self, session_id):
            return {
                "session_id": session_id,
                "project_id": uuid4(),
                "project_key": "fake-project",
                "original_request": "Create a plan",
                "input_mode": "text",
                "intake": {},
            }

        async def save_questions_from_graph(self, **kwargs):
            raise AssertionError("This workflow path should not ask questions")

        async def persist_plan_from_graph(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def build_context_capsules_for_plan(self, **kwargs):
            return [uuid4()]

    registry = SkillRegistry(load_builtin_skill_manifests())
    registry.register(FakePlanningSkill())

    graph = build_planning_graph(
        None,
        checkpointer=None,
        store=InMemoryStore(),
        registry=registry,
        planning_service=FakePlanningService(),
        capsule_service=object(),
    )

    result = await graph.ainvoke({"session_id": uuid4(), "errors": []})

    assert result["plan_version_id"]
    assert len(result["context_capsule_ids"]) == 1
