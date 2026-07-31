from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.services.planning_service import PlanningService
from agent_core.services.context_capsule_service import ContextCapsuleService
from agent_core.skills import build_skill_registry
from agent_core.skills.base import SkillContext
from agent_core.skills.registry import SkillRegistry
from agent_core.skills.router import SkillRouter
from agent_core.workflow.skill_node import SkillNodeAdapter
from agent_core.workflow.state import PlanningGraphState


def make_nodes(
    db: AsyncSession | None,
    *,
    registry: SkillRegistry | None = None,
    planning_service: Any | None = None,
    capsule_service: Any | None = None,
):
    if db is None and planning_service is None:
        raise ValueError("A database session or planning service is required")

    planning_service = planning_service or PlanningService(db)
    capsule_service = capsule_service or ContextCapsuleService(db)

    registry = registry or build_skill_registry()
    skill_router = SkillRouter(registry)
    skill_node = SkillNodeAdapter(registry)

    async def load_session(
        state: PlanningGraphState,
        *,
        store: BaseStore,
    ) -> PlanningGraphState:
        context = await planning_service.load_session_context(state["session_id"])

        return {
            **state,
            **context,
            "current_intent": context["original_request"],
            "skill_results": state.get("skill_results", []),
        }

    async def route_skill(
        state: PlanningGraphState,
        *,
        store: BaseStore,
    ) -> PlanningGraphState:
        skill_context = SkillContext(
            project_key=state["project_key"],
            session_id=str(state["session_id"]),
            metadata={
                "input_mode": state["input_mode"],
            },
        )

        route = skill_router.route(
            intent=state["current_intent"],
            context=skill_context,
        )

        # Optional: save route decision in LangGraph store.
        store.put(
            ("projects", state["project_key"], "skill_routes"),
            route.skill_name,
            {
                "intent": state["current_intent"],
                "confidence": route.confidence,
                "reason": route.reason,
            },
        )

        return {
            **state,
            "selected_skill": route.skill_name,
            "skill_confidence": route.confidence,
        }

    async def run_selected_skill(
        state: PlanningGraphState,
        *,
        store: BaseStore,
    ) -> PlanningGraphState:
        skill_context = SkillContext(
            project_key=state["project_key"],
            session_id=str(state["session_id"]),
        )

        result = await skill_node.run(
            skill_name=state["selected_skill"],
            intent=state["current_intent"],
            context=skill_context,
            input_data={
                "original_request": state["original_request"],
                "intake": state["intake"],
                "chunk_summaries": state.get("chunk_summaries", []),
            },
        )

        skill_results = state.get("skill_results", [])
        skill_results.append(result.model_dump(mode="json"))

        new_state: PlanningGraphState = {
            **state,
            "skill_results": skill_results,
        }

        if result.skill_name == "ambiguity_assessment":
            if result.questions:
                new_state["ambiguity_status"] = "needs_clarification"
                new_state["clarification_questions"] = result.questions
            else:
                new_state["ambiguity_status"] = "ready_for_planning"

        if result.skill_name == "planning_decomposition":
            new_state["plan"] = result.output

        return new_state

    async def save_clarification_questions(
        state: PlanningGraphState,
        *,
        store: BaseStore,
    ) -> PlanningGraphState:
        await planning_service.save_questions_from_graph(
            session_id=state["session_id"],
            project_id=state["project_id"],
            questions=state["clarification_questions"],
        )
        return state

    async def persist_plan(
        state: PlanningGraphState,
        *,
        store: BaseStore,
    ) -> PlanningGraphState:
        plan_version = await planning_service.persist_plan_from_graph(
            session_id=state["session_id"],
            plan_json=state["plan"],
        )

        return {
            **state,
            "plan_version_id": plan_version.id,
        }

    async def build_context_capsules(
        state: PlanningGraphState,
        *,
        store: BaseStore,
    ) -> PlanningGraphState:
        capsule_ids = await planning_service.build_context_capsules_for_plan(
            plan_version_id=state["plan_version_id"],
        )

        return {
            **state,
            "context_capsule_ids": capsule_ids,
        }

    return {
        "load_session": load_session,
        "route_skill": route_skill,
        "run_selected_skill": run_selected_skill,
        "save_clarification_questions": save_clarification_questions,
        "persist_plan": persist_plan,
        "build_context_capsules": build_context_capsules,
    }
